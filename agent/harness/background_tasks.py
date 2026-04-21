"""
Background Task Registry
========================
Shared in-memory store for background Bash processes and Agent tasks.
Both BashTool and AgentTool write results here; TaskOutput reads them.

Entry schema
------------
  task_id    : str  — "bg_<hex>"
  kind       : "bash" | "agent"
  label      : str  — short description shown in the UI
  status     : "running" | "completed" | "failed" | "cancelled"
  output     : str  — accumulated stdout/stderr (bash) or final text (agent)
  exit_code  : int | None  — bash only
  started_at : float  — time.monotonic()
  ended_at   : float | None
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackgroundTask:
    task_id: str
    kind: str           # "bash" | "agent"
    label: str
    status: str = "running"
    output: str = ""
    exit_code: Optional[int] = None
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None
    # Internal handle for cancellation
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)  # type: ignore[name-defined]

    def elapsed_s(self) -> float:
        end = self.ended_at or time.monotonic()
        return end - self.started_at


class BackgroundTaskRegistry:
    """Process-level singleton. All tool instances share one registry."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}

    def new_id(self) -> str:
        return f"bg_{uuid.uuid4().hex[:8]}"

    def register(self, task: BackgroundTask) -> None:
        self._tasks[task.task_id] = task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def all(self) -> list[BackgroundTask]:
        return list(self._tasks.values())

    def cancel(self, task_id: str) -> bool:
        t = self._tasks.get(task_id)
        if t is None:
            return False
        if t.status != "running":
            return False
        t.status = "cancelled"
        t.ended_at = time.monotonic()
        if t._asyncio_task and not t._asyncio_task.done():
            t._asyncio_task.cancel()
        if t._process:
            try:
                t._process.kill()
            except Exception:
                pass
        return True

    def reset(self) -> None:
        """Cancel all running tasks (called on session reset)."""
        for t in list(self._tasks.values()):
            if t.status == "running":
                self.cancel(t.task_id)
        self._tasks.clear()


# Module-level singleton shared by all tool instances
REGISTRY = BackgroundTaskRegistry()
