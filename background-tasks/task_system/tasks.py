from __future__ import annotations

import os
import time
from typing import Any, Dict

from .registry import task


@task("fake_long_analysis")
def fake_long_analysis(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fake task: sleeps and emits progress via ctx['progress'] callback.
    """
    steps = int(payload.get("steps", 8))
    for i in range(steps):
        time.sleep(0.6)
        ctx["progress"]((i + 1) / steps, f"Step {i+1}/{steps}")
    return {"summary": "Fake analysis complete", "steps": steps}


@task("pdf_quick_stats")
def pdf_quick_stats(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Placeholder for real PDF analysis: just reads file size and simulates work.
    """
    file_ref = ctx.get("file_ref") or {}
    path = file_ref.get("path")
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Missing file at {path}")

    size = os.path.getsize(path)

    # Simulate doing something “pdf-ish”
    ctx["progress"](0.2, "Opened PDF")
    time.sleep(0.5)
    ctx["progress"](0.6, "Scanning pages (simulated)")
    time.sleep(0.8)
    ctx["progress"](0.9, "Building summary (simulated)")
    time.sleep(0.4)

    return {
        "file_name": file_ref.get("name"),
        "bytes": size,
        "note": "This is placeholder output; swap in real PDF parsing later.",
    }
