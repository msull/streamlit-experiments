from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from diskcache import Deque, Index


@dataclass
class Task:
    task_id: str
    task_type: str
    created_at: float
    payload: Dict[str, Any]
    file_ref: Optional[Dict[str, Any]] = None  # e.g. {"path": "...", "name": "..."}
    # Optional routing/metadata:
    priority: int = 0


class TaskStore:
    """
    A tight abstraction around DiskCache primitives:
      - Deque: work queue
      - Index: task_state, task_results, task_events

    This keeps swapping to Redis/Celery later straightforward.
    """

    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.queue = Deque(directory=os.path.join(data_dir, "queue"))
        self.state = Index(os.path.join(data_dir, "state"))
        self.results = Index(os.path.join(data_dir, "results"))
        self.events = Index(os.path.join(data_dir, "events"))

    # ---------- enqueue / dequeue ----------

    def enqueue(self, task_type: str, payload: Dict[str, Any], file_ref: Optional[Dict[str, Any]] = None) -> str:
        task_id = uuid.uuid4().hex
        task = Task(
            task_id=task_id,
            task_type=task_type,
            created_at=time.time(),
            payload=payload,
            file_ref=file_ref,
        )
        # Initialize state + events first so UI can immediately render it
        self.state[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "created_at": task.created_at,
            "started_at": None,
            "finished_at": None,
            "worker": None,
            "error": None,
        }
        self.events[task_id] = [(time.time(), "queued", "Task queued")]
        self.queue.append(asdict(task))
        return task_id

    def try_dequeue(self) -> Optional[Dict[str, Any]]:
        try:
            return self.queue.popleft()
        except IndexError:
            return None

    # ---------- state updates ----------

    def set_running(self, task_id: str, worker_name: str):
        s = dict(self.state.get(task_id, {}))
        s.update({
            "status": "running",
            "progress": float(s.get("progress", 0.0) or 0.0),
            "message": "Running",
            "started_at": time.time(),
            "worker": worker_name,
            "error": None,
        })
        self.state[task_id] = s
        self.append_event(task_id, "running", f"Started on worker {worker_name}")

    def set_progress(self, task_id: str, progress: float, message: str | None = None):
        s = dict(self.state.get(task_id, {}))
        s["progress"] = float(max(0.0, min(1.0, progress)))
        if message is not None:
            s["message"] = message
        self.state[task_id] = s
        if message:
            self.append_event(task_id, "progress", message)

    def set_succeeded(self, task_id: str, result: Dict[str, Any], message: str = "Succeeded"):
        s = dict(self.state.get(task_id, {}))
        s.update({
            "status": "succeeded",
            "progress": 1.0,
            "message": message,
            "finished_at": time.time(),
        })
        self.state[task_id] = s
        self.results[task_id] = result
        self.append_event(task_id, "succeeded", message)

    def set_failed(self, task_id: str, error: str, message: str = "Failed"):
        s = dict(self.state.get(task_id, {}))
        s.update({
            "status": "failed",
            "message": message,
            "finished_at": time.time(),
            "error": error,
        })
        self.state[task_id] = s
        self.append_event(task_id, "failed", f"{message}: {error}")

    def append_event(self, task_id: str, kind: str, text: str):
        ev = list(self.events.get(task_id, []))
        ev.append((time.time(), kind, text))
        self.events[task_id] = ev

    # ---------- read APIs for UI ----------

    def get_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.state.get(task_id)

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.results.get(task_id)

    def get_events(self, task_id: str) -> list[tuple[float, str, str]]:
        return list(self.events.get(task_id, []))

    def list_recent(self, limit: int = 50) -> list[Dict[str, Any]]:
        items = [self.state[tid] for tid in self.state.keys()]
        items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return items[:limit]
