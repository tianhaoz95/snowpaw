"""Tools: Task & Project Management — TodoWrite, TaskCreate/Get/List/Update/Stop/Output.

Design
------
* TodoWrite   — writes a markdown checklist to ``.cyberpaw_todos.md`` in the
                working directory.  Simple and persistent; no in-memory state.

* Task*       — lightweight in-memory task store keyed by ``session_id``
                (same pattern as ReplTool's namespace dict).  Each session
                owns its own task list; tasks are discarded on session reset.

Task schema
-----------
  id          : int  — auto-increment per session, starts at 1
  subject     : str  — short title
  description : str  — longer detail (optional)
  status      : "pending" | "in_progress" | "completed" | "cancelled"
  owner       : str  — free-form (default "agent")
  created_at  : ISO-8601 string

TaskStop cancels the asyncio.Task tracked in ``_running`` if one exists for
that task id; otherwise it just marks the status as "cancelled".

TaskOutput is a no-op stub that returns the task's summary — CyberPaw does not
run background asyncio workers yet, but the API surface is in place.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from harness.tool_registry import Tool, ToolContext, ToolResult


# ── Shared in-memory store ────────────────────────────────────────────────────

class _TaskStore:
    """Singleton-style store: session_id → list of task dicts."""

    def __init__(self) -> None:
        # session_id → {"next_id": int, "tasks": {id: dict}}
        self._sessions: dict[str, dict[str, Any]] = {}
        # (session_id, task_id) → asyncio.Task — for TaskStop
        self._running: dict[tuple[str, int], asyncio.Task] = {}

    def _session(self, sid: str) -> dict[str, Any]:
        if sid not in self._sessions:
            self._sessions[sid] = {"next_id": 1, "tasks": {}}
        return self._sessions[sid]

    def create(self, sid: str, subject: str, description: str = "",
               owner: str = "agent") -> dict:
        s = self._session(sid)
        tid = s["next_id"]
        s["next_id"] += 1
        task = {
            "id": tid,
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": owner,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        s["tasks"][tid] = task
        return task

    def get(self, sid: str, tid: int) -> dict | None:
        return self._session(sid)["tasks"].get(tid)

    def list_all(self, sid: str) -> list[dict]:
        return list(self._session(sid)["tasks"].values())

    def update(self, sid: str, tid: int, **fields) -> dict | None:
        task = self.get(sid, tid)
        if task is None:
            return None
        allowed = {"subject", "description", "status", "owner"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                task[k] = v
        return task

    def register_running(self, sid: str, tid: int, atask: asyncio.Task) -> None:
        self._running[(sid, tid)] = atask

    def stop(self, sid: str, tid: int) -> bool:
        """Cancel the asyncio.Task if tracked; mark status cancelled. Returns True if found."""
        key = (sid, tid)
        atask = self._running.pop(key, None)
        task = self.get(sid, tid)
        if task:
            task["status"] = "cancelled"
        if atask and not atask.done():
            atask.cancel()
            return True
        return task is not None

    def reset_session(self, sid: str) -> None:
        """Drop all tasks for a session (called on session reset in main.py)."""
        self._sessions.pop(sid, None)
        # Cancel any running asyncio tasks for that session
        to_remove = [k for k in self._running if k[0] == sid]
        for key in to_remove:
            atask = self._running.pop(key)
            if not atask.done():
                atask.cancel()


# Module-level singleton — all task tool instances share the same store.
_STORE = _TaskStore()


# ── TodoWrite ─────────────────────────────────────────────────────────────────

class TodoWriteTool(Tool):
    name = "TodoWrite"
    description = (
        "Write a persistent to-do list to .cyberpaw_todos.md in the current "
        "working directory.  Pass a list of todo items; the file is completely "
        "overwritten each call so you always have the latest state.  "
        "Use this to track multi-step work across conversation turns."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text":   {"type": "string",  "description": "Todo item text."},
                        "done":   {"type": "boolean", "description": "True if completed."},
                    },
                    "required": ["text"],
                },
                "description": "Ordered list of todo items.",
            },
        },
        "required": ["todos"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        todos: list[dict] = input.get("todos", [])
        lines = ["# CyberPaw To-Do List\n"]
        for item in todos:
            text = item.get("text", "").strip()
            done = bool(item.get("done", False))
            check = "x" if done else " "
            lines.append(f"- [{check}] {text}\n")

        content = "".join(lines)
        dest = os.path.join(ctx.working_directory, ".cyberpaw_todos.md")
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(str(e))

        total = len(todos)
        done_count = sum(1 for t in todos if t.get("done"))
        summary = f"Wrote {total} todos ({done_count} done) to .cyberpaw_todos.md"
        return ToolResult.ok(f"Saved {total} todos to {dest}", summary)


# ── TaskCreate ────────────────────────────────────────────────────────────────

class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = (
        "Create a new task in the session's task list.  "
        "Returns the new task's ID which you can use with TaskGet/TaskUpdate/TaskStop."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Short title for the task.",
            },
            "description": {
                "type": "string",
                "description": "Longer description or goal for the task (optional).",
            },
            "owner": {
                "type": "string",
                "description": "Who owns the task, e.g. 'agent' or 'user' (default: 'agent').",
            },
        },
        "required": ["subject"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        subject = input["subject"].strip()
        if not subject:
            return ToolResult.error("subject must not be empty")
        description = input.get("description", "")
        owner = input.get("owner") or "agent"
        task = _STORE.create(ctx.session_id, subject, description, owner)
        output = _fmt_task(task)
        return ToolResult.ok(output, f"Created task #{task['id']}: {subject[:60]}")


# ── TaskGet ───────────────────────────────────────────────────────────────────

class TaskGetTool(Tool):
    name = "TaskGet"
    description = "Retrieve full details of a task by its numeric ID."
    input_schema = {
        "type": "object",
        "properties": {
            "id": {
                "type": "integer",
                "description": "Task ID returned by TaskCreate.",
            },
        },
        "required": ["id"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        tid = int(input["id"])
        task = _STORE.get(ctx.session_id, tid)
        if task is None:
            return ToolResult.error(f"Task #{tid} not found")
        return ToolResult.ok(_fmt_task(task), f"Task #{tid}: {task['subject'][:60]}")


# ── TaskList ──────────────────────────────────────────────────────────────────

class TaskListTool(Tool):
    name = "TaskList"
    description = (
        "List all tasks for the current session with their IDs, subjects, "
        "statuses, and owners."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled", "all"],
                "description": "Only return tasks with this status.  Defaults to 'all'.",
            },
        },
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        tasks = _STORE.list_all(ctx.session_id)
        status_filter = (input.get("status_filter") or "all").lower()
        if status_filter != "all":
            tasks = [t for t in tasks if t["status"] == status_filter]

        if not tasks:
            msg = "No tasks found."
            if status_filter != "all":
                msg = f"No tasks with status '{status_filter}'."
            return ToolResult.ok(msg, msg)

        lines = [f"{'ID':<4} {'Status':<12} {'Owner':<12} Subject"]
        lines.append("-" * 60)
        for t in tasks:
            lines.append(
                f"{t['id']:<4} {t['status']:<12} {t['owner']:<12} {t['subject']}"
            )
        output = "\n".join(lines)
        summary = f"{len(tasks)} task(s)" + (f" [{status_filter}]" if status_filter != "all" else "")
        return ToolResult.ok(output, summary)


# ── TaskUpdate ────────────────────────────────────────────────────────────────

class TaskUpdateTool(Tool):
    name = "TaskUpdate"
    description = (
        "Update a task's subject, description, status, or owner.  "
        "Valid status values: pending, in_progress, completed, cancelled."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "id":          {"type": "integer", "description": "Task ID to update."},
            "subject":     {"type": "string",  "description": "New subject/title."},
            "description": {"type": "string",  "description": "New description."},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled"],
                "description": "New status.",
            },
            "owner": {"type": "string", "description": "New owner."},
        },
        "required": ["id"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        tid = int(input["id"])
        task = _STORE.update(
            ctx.session_id, tid,
            subject=input.get("subject"),
            description=input.get("description"),
            status=input.get("status"),
            owner=input.get("owner"),
        )
        if task is None:
            return ToolResult.error(f"Task #{tid} not found")
        return ToolResult.ok(_fmt_task(task), f"Updated task #{tid}: {task['subject'][:60]}")


# ── TaskStop ──────────────────────────────────────────────────────────────────

class TaskStopTool(Tool):
    name = "TaskStop"
    description = (
        "Cancel a running task or background process. "
        "Pass either a numeric task ID or a string background task_id like 'bg_a1b2c3d4'. "
        "Cancels the underlying process or asyncio task and marks status as 'cancelled'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "id": {
                "description": "Numeric task ID or string background task_id (e.g. 'bg_a1b2c3d4').",
            },
        },
        "required": ["id"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        from harness.background_tasks import REGISTRY

        raw_id = input["id"]

        if isinstance(raw_id, str) and raw_id.startswith("bg_"):
            found = REGISTRY.cancel(raw_id)
            if not found:
                return ToolResult.error(f"Background task '{raw_id}' not found or already finished")
            return ToolResult.ok(f"Background task '{raw_id}' cancelled.", f"Stopped {raw_id}")

        try:
            tid = int(raw_id)
        except (ValueError, TypeError):
            return ToolResult.error(f"Invalid task id: {raw_id!r}")
        found = _STORE.stop(ctx.session_id, tid)
        if not found:
            return ToolResult.error(f"Task #{tid} not found")
        return ToolResult.ok(f"Task #{tid} cancelled.", f"Stopped task #{tid}")


# ── TaskOutput ────────────────────────────────────────────────────────────────

class TaskOutputTool(Tool):
    name = "TaskOutput"
    description = (
        "Get the current output / result for a task or background process. "
        "Pass either a numeric task ID (from TaskCreate) or a string task_id "
        "like 'bg_a1b2c3d4' returned by Bash/Agent when run_in_background=true. "
        "For background tasks, status is 'running', 'completed', 'failed', or 'cancelled'. "
        "Poll until status is no longer 'running' to get the full output."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "id": {
                "description": "Numeric task ID or string background task_id (e.g. 'bg_a1b2c3d4').",
            },
        },
        "required": ["id"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        from harness.background_tasks import REGISTRY

        raw_id = input["id"]

        # String background task ID (e.g. "bg_a1b2c3d4")
        if isinstance(raw_id, str) and raw_id.startswith("bg_"):
            bg = REGISTRY.get(raw_id)
            if bg is None:
                return ToolResult.error(f"Background task '{raw_id}' not found")
            elapsed = f"{bg.elapsed_s():.1f}s"
            lines = [
                f"task_id : {bg.task_id}",
                f"kind    : {bg.kind}",
                f"label   : {bg.label}",
                f"status  : {bg.status}",
                f"elapsed : {elapsed}",
            ]
            if bg.exit_code is not None:
                lines.append(f"exit    : {bg.exit_code}")
            if bg.output:
                lines.append(f"\n--- output ---\n{bg.output}")
            elif bg.status == "running":
                lines.append("\n(still running — poll again later)")
            output = "\n".join(lines)
            return ToolResult.ok(output, f"{raw_id} [{bg.status}] {elapsed}")

        # Numeric task ID from _STORE
        try:
            tid = int(raw_id)
        except (ValueError, TypeError):
            return ToolResult.error(f"Invalid task id: {raw_id!r}")
        task = _STORE.get(ctx.session_id, tid)
        if task is None:
            return ToolResult.error(f"Task #{tid} not found")
        output = _fmt_task(task)
        return ToolResult.ok(output, f"Output for task #{tid}: {task['status']}")


# ── Shared reset helper (called from main.py on session reset) ────────────────

def reset_task_session(session_id: str) -> None:
    """Clear all tasks and cancel running asyncio tasks for a session."""
    from harness.background_tasks import REGISTRY
    _STORE.reset_session(session_id)
    REGISTRY.reset()


# ── Formatting helper ─────────────────────────────────────────────────────────

def _fmt_task(task: dict) -> str:
    lines = [
        f"Task #{task['id']}",
        f"  Subject    : {task['subject']}",
        f"  Status     : {task['status']}",
        f"  Owner      : {task['owner']}",
        f"  Created    : {task['created_at']}",
    ]
    if task.get("description"):
        lines.append(f"  Description: {task['description']}")
    return "\n".join(lines)
