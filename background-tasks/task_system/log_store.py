from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional

from diskcache import Deque


@dataclass
class LogEntry:
    timestamp: float
    level: str
    logger_name: str
    message: str
    worker: Optional[str] = None


class DiskCacheLogHandler(logging.Handler):
    """logging.Handler that writes records to a DiskCache Deque (circular buffer)."""

    def __init__(self, data_dir: str, worker_name: str = "unknown", maxlen: int = 200):
        super().__init__()
        self.deque = Deque(directory=os.path.join(data_dir, "logs"))
        self.worker_name = worker_name
        self.maxlen = maxlen

    def emit(self, record: logging.LogRecord):
        try:
            entry = LogEntry(
                timestamp=record.created,
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
                worker=self.worker_name,
            )
            self.deque.append(asdict(entry))
            while len(self.deque) > self.maxlen:
                try:
                    self.deque.popleft()
                except IndexError:
                    break
        except Exception:
            self.handleError(record)


def read_recent_logs(data_dir: str, limit: int = 50) -> list[dict]:
    """Read the most recent log entries from the shared deque."""
    deque = Deque(directory=os.path.join(data_dir, "logs"))
    entries = list(deque)
    return entries[-limit:]
