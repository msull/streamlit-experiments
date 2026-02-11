from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any, Dict, Optional

import streamlit as st

from task_system.store import TaskStore
from task_system.registry import list_task_types
from task_system import tasks  # noqa: F401 (register task types)

DATA_DIR = "data"
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Singletons — created once per server lifetime via @st.cache_resource
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_app():
    from task_system.worker import start_embedded_worker
    from task_system.log_store import DiskCacheLogHandler

    app_store = TaskStore(DATA_DIR)

    worker_logger = logging.getLogger("task_system.worker")
    # Clear any handlers from a previous init (e.g. after "Clear all task data")
    worker_logger.handlers.clear()
    handler = DiskCacheLogHandler(DATA_DIR, worker_name="embedded-1")
    handler.setFormatter(logging.Formatter("%(message)s"))
    worker_logger.addHandler(handler)
    worker_logger.setLevel(logging.INFO)

    thread, stop_event = start_embedded_worker(app_store, "embedded-1", 0.5)
    return app_store, thread, stop_event


store, worker_thread, worker_stop = _init_app()


# ---------------------------------------------------------------------------
# Page config & session state
# ---------------------------------------------------------------------------

st.set_page_config(page_title="DiskCache Tasks Prototype", layout="wide")
st.title("Streamlit + DiskCache Background Tasks")

# Hide the "running" indicator that flashes on every fragment poll
st.markdown(
    '<style>[data-testid="stStatusWidget"] { display: none; }</style>',
    unsafe_allow_html=True,
)

if "chat" not in st.session_state:
    st.session_state.chat = []
if "known_status" not in st.session_state:
    st.session_state.known_status = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def save_upload(file) -> Dict[str, Any]:
    ts = int(time.time() * 1000)
    safe_name = file.name.replace("/", "_")
    path = os.path.join(UPLOAD_DIR, f"{ts}_{safe_name}")
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return {"path": path, "name": file.name}


# ---------------------------------------------------------------------------
# Sidebar — worker status & logs
# ---------------------------------------------------------------------------

with st.sidebar:
    st.subheader("Worker")

    if worker_thread.is_alive():
        st.success("Running", icon="✅")
    else:
        st.error("Stopped", icon="❌")

    queue_depth = len(store.queue)
    st.metric("Queue depth", queue_depth)

    st.divider()
    st.subheader("Worker Logs")

    @st.fragment(run_every="3s")
    def log_panel():
        from task_system.log_store import read_recent_logs
        logs = read_recent_logs(DATA_DIR, limit=20)
        if not logs:
            st.caption("No log entries yet.")
        else:
            for entry in reversed(logs):
                ts = time.strftime("%H:%M:%S", time.localtime(entry["timestamp"]))
                level = entry.get("level", "INFO")
                msg = entry.get("message", "")
                if level == "ERROR":
                    st.markdown(f"`{ts}` :red[{msg}]")
                else:
                    st.markdown(f"`{ts}` {msg}")

    log_panel()

    st.divider()
    if st.button("Clear all task data"):
        for subdir in ["queue", "state", "results", "events", "logs"]:
            path = os.path.join(DATA_DIR, subdir)
            if os.path.exists(path):
                shutil.rmtree(path)
        st.session_state.chat = []
        st.session_state.known_status = {}
        # Force cached singleton to reinitialize with fresh DiskCache connections
        _init_app.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

left, right = st.columns([0.6, 0.4])

# ---------------------------------------------------------------------------
# Left column — chat interface
# ---------------------------------------------------------------------------

with left:
    st.subheader("1) Upload a file (optional)")
    uploaded = st.file_uploader("Upload file", type=None)
    file_ref: Optional[Dict[str, Any]] = None
    if uploaded is not None:
        file_ref = save_upload(uploaded)
        st.success(f"Saved upload: {file_ref['name']}")

    st.subheader("2) Submit a task")
    task_type = st.selectbox("Task type", options=list_task_types(), index=0)
    steps = st.slider("Fake steps (for fake_long_analysis)", 3, 20, 8)

    user_msg = st.text_input("User message", placeholder='e.g. "Run analysis A on this PDF"')

    cols = st.columns([0.25, 0.75])
    with cols[0]:
        if st.button("Send / Start task", type="primary"):
            if user_msg:
                st.session_state.chat.append({"role": "user", "text": user_msg, "task_id": None})

            payload = {"steps": steps}
            if task_type != "fake_long_analysis":
                payload = {}

            if task_type == "pdf_quick_stats" and not file_ref:
                st.session_state.chat.append({
                    "role": "assistant",
                    "text": "Please upload a file first for pdf_quick_stats.",
                    "task_id": None,
                })
            else:
                task_id = store.enqueue(task_type=task_type, payload=payload, file_ref=file_ref)
                st.session_state.chat.append({
                    "role": "assistant",
                    "text": f"Started task `{task_type}` (id={task_id[:8]}...)",
                    "task_id": task_id,
                })
                st.session_state.known_status[task_id] = "queued"
            st.rerun()

    st.subheader("Chat transcript")
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.write(msg["text"])


# ---------------------------------------------------------------------------
# Right column — task dashboard (auto-refreshing fragment)
# ---------------------------------------------------------------------------

with right:
    st.subheader("Task dashboard")

    @st.fragment(run_every="2s")
    def task_poll_panel():
        recent = store.list_recent(limit=30)

        # Detect status transitions → toast notifications + chat messages
        needs_rerun = False
        for s in recent:
            task_id = s["task_id"]
            prev = st.session_state.known_status.get(task_id)
            cur = s.get("status")
            if prev != cur:
                st.session_state.known_status[task_id] = cur
                if cur == "succeeded":
                    st.toast(f"Task {task_id[:8]} completed: {s.get('task_type')}", icon="✅")
                    st.session_state.chat.append({
                        "role": "assistant",
                        "text": f"Task {task_id[:8]} finished: {s.get('task_type')}",
                        "task_id": task_id,
                    })
                    needs_rerun = True
                elif cur == "failed":
                    st.toast(f"Task {task_id[:8]} failed: {s.get('task_type')}", icon="❌")
                    st.session_state.chat.append({
                        "role": "assistant",
                        "text": f"Task {task_id[:8]} failed: {s.get('task_type')}",
                        "task_id": task_id,
                    })
                    needs_rerun = True

        # Empty state
        if not recent:
            st.info("No tasks yet. Submit one from the left panel.")
            return

        # Render task cards
        for s in recent[:12]:
            task_id = s["task_id"]
            status = s.get("status", "unknown")
            icon = {"queued": "⏳", "running": "🔄", "succeeded": "✅", "failed": "❌"}.get(status, "❓")

            with st.container(border=True):
                st.markdown(f"{icon} **{s['task_type']}** `{task_id[:8]}...`")
                st.progress(float(s.get("progress", 0.0) or 0.0))

                # Timing
                created = s.get("created_at")
                started = s.get("started_at")
                finished = s.get("finished_at")
                parts = []
                if created:
                    parts.append(f"queued {time.strftime('%H:%M:%S', time.localtime(created))}")
                if started and finished:
                    parts.append(f"took {finished - started:.1f}s")
                elif started:
                    parts.append(f"running {time.time() - started:.1f}s")

                worker = s.get("worker") or "pending"
                st.caption(f"{status} | {' | '.join(parts)} | worker={worker}")

                with st.expander("Events / Result", expanded=False):
                    for ts, kind, txt in store.get_events(task_id)[-20:]:
                        st.write(f"- {time.strftime('%H:%M:%S', time.localtime(ts))} [{kind}] {txt}")
                    if status == "succeeded":
                        st.json(store.get_result(task_id) or {})
                    if status == "failed":
                        st.code(s.get("error") or "", language="text")

        # Full page rerun to update chat transcript with completion messages
        if needs_rerun:
            st.rerun()

    task_poll_panel()
