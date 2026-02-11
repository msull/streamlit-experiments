from __future__ import annotations

import argparse
import logging
import random
import threading
import time
import traceback
from typing import Any, Dict

from .store import TaskStore
from .registry import get as get_task_fn
from . import tasks  # noqa: F401  (ensures task decorators register tasks)

logger = logging.getLogger("task_system.worker")


def run_worker(
    data_dir: str | None = None,
    worker_name: str = "worker-1",
    poll_interval: float = 0.5,
    stop_event: threading.Event | None = None,
    store: TaskStore | None = None,
):
    if store is None:
        store = TaskStore(data_dir=data_dir)
    logger.info("Worker %s started", worker_name)

    while not (stop_event and stop_event.is_set()):
        item = store.try_dequeue()
        if item is None:
            if stop_event:
                stop_event.wait(timeout=poll_interval)
            else:
                time.sleep(poll_interval)
            continue

        task_id = item["task_id"]
        task_type = item["task_type"]
        payload = item.get("payload") or {}
        file_ref = item.get("file_ref")

        logger.info("Dequeued task %s (%s)", task_id[:8], task_type)

        # De-dup / idempotency: if already finished, skip
        s = store.get_state(task_id) or {}
        if s.get("status") in ("succeeded", "failed"):
            logger.debug("Skipping already-finished task %s", task_id[:8])
            continue

        store.set_running(task_id, worker_name)
        logger.info("Running task %s on %s", task_id[:8], worker_name)

        def progress(p: float, msg: str, _tid=task_id):
            store.set_progress(_tid, p, msg)
            logger.debug("Task %s progress %.0f%%: %s", _tid[:8], p * 100, msg)

        ctx: Dict[str, Any] = {
            "task_id": task_id,
            "task_type": task_type,
            "file_ref": file_ref,
            "progress": progress,
        }

        try:
            fn = get_task_fn(task_type)
            time.sleep(random.uniform(0.0, 0.2))
            result = fn(payload, ctx)
            store.set_succeeded(task_id, result)
            logger.info("Task %s succeeded", task_id[:8])
        except Exception as e:
            err = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            store.set_failed(task_id, error=err)
            logger.error("Task %s failed: %s", task_id[:8], e)


def start_embedded_worker(
    store: TaskStore,
    worker_name: str = "embedded-1",
    poll_interval: float = 0.5,
) -> tuple[threading.Thread, threading.Event]:
    """Start a daemon worker thread sharing the given store. Returns (thread, stop_event)."""
    stop_event = threading.Event()
    t = threading.Thread(
        target=run_worker,
        kwargs=dict(store=store, worker_name=worker_name, poll_interval=poll_interval, stop_event=stop_event),
        daemon=True,
        name=f"task-worker-{worker_name}",
    )
    t.start()
    return t, stop_event


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--worker-name", default="worker-1")
    ap.add_argument("--poll-interval", type=float, default=0.2)
    args = ap.parse_args()
    run_worker(args.data_dir, args.worker_name, args.poll_interval)


if __name__ == "__main__":
    main()
