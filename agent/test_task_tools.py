"""Quick smoke test for Task & Project Management tools — no model needed."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

# Make sure the agent package root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from harness.tool_registry import ToolContext
from harness.permissions import PermissionMode
from tools.task_tools import (
    TodoWriteTool, TaskCreateTool, TaskGetTool, TaskListTool,
    TaskUpdateTool, TaskStopTool, TaskOutputTool, reset_task_session,
    _STORE,
)

SESSION = "test-session-001"


def make_ctx(working_directory: str) -> ToolContext:
    return ToolContext(
        working_directory=working_directory,
        permission_mode=PermissionMode.AUTO_ALL,
        session_id=SESSION,
    )


async def test_todo_write(tmpdir: str) -> None:
    print("--- TodoWrite ---")
    tool = TodoWriteTool()
    ctx = make_ctx(tmpdir)
    result = await tool.call(
        {"todos": [
            {"text": "Write unit tests", "done": False},
            {"text": "Implement feature", "done": True},
            {"text": "Deploy", "done": False},
        ]},
        ctx,
    )
    assert not result.is_error, f"Expected ok, got error: {result.output}"
    dest = os.path.join(tmpdir, ".snowpaw_todos.md")
    assert os.path.exists(dest), "Todos file not created"
    content = open(dest).read()
    assert "- [ ] Write unit tests" in content
    assert "- [x] Implement feature" in content
    print(f"  output : {result.output}")
    print(f"  summary: {result.summary}")
    print(f"  file   :\n{content}")
    print("  PASS")


async def test_task_lifecycle(tmpdir: str) -> None:
    print("--- TaskCreate ---")
    create = TaskCreateTool()
    ctx = make_ctx(tmpdir)
    r = await create.call(
        {"subject": "Refactor auth module", "description": "Move to OAuth2", "owner": "agent"},
        ctx,
    )
    assert not r.is_error
    assert "#1" in r.summary
    print(f"  summary: {r.summary}")
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskCreate (second) ---")
    r2 = await create.call({"subject": "Write docs"}, ctx)
    assert not r2.is_error
    assert "#2" in r2.summary
    print(f"  summary: {r2.summary}")
    print("  PASS")

    print("--- TaskGet ---")
    get = TaskGetTool()
    r = await get.call({"id": 1}, ctx)
    assert not r.is_error
    assert "Refactor auth module" in r.output
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskGet (missing) ---")
    r = await get.call({"id": 99}, ctx)
    assert r.is_error
    print(f"  error  : {r.output}")
    print("  PASS")

    print("--- TaskList (all) ---")
    lst = TaskListTool()
    r = await lst.call({}, ctx)
    assert not r.is_error
    assert "Refactor auth module" in r.output
    assert "Write docs" in r.output
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskList (filter: pending) ---")
    r = await lst.call({"status_filter": "pending"}, ctx)
    assert not r.is_error
    assert "pending" in r.output
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskUpdate ---")
    upd = TaskUpdateTool()
    r = await upd.call({"id": 1, "status": "in_progress", "owner": "bot"}, ctx)
    assert not r.is_error
    assert "in_progress" in r.output
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskOutput (stub) ---")
    out = TaskOutputTool()
    r = await out.call({"id": 1}, ctx)
    assert not r.is_error
    assert "in_progress" in r.output
    print(f"  output :\n{r.output}")
    print("  PASS")

    print("--- TaskStop ---")
    stop = TaskStopTool()
    r = await stop.call({"id": 1}, ctx)
    assert not r.is_error
    assert "cancelled" in r.output
    # Confirm status changed
    task = _STORE.get(SESSION, 1)
    assert task["status"] == "cancelled"
    print(f"  output : {r.output}")
    print("  PASS")

    print("--- TaskStop (missing) ---")
    r = await stop.call({"id": 99}, ctx)
    assert r.is_error
    print(f"  error  : {r.output}")
    print("  PASS")


async def test_session_reset(tmpdir: str) -> None:
    print("--- Session Reset ---")
    # Create a task under a different session
    new_session = "reset-test-session"
    create = TaskCreateTool()
    ctx = ToolContext(
        working_directory=tmpdir,
        permission_mode=PermissionMode.AUTO_ALL,
        session_id=new_session,
    )
    await create.call({"subject": "Should be gone after reset"}, ctx)
    task = _STORE.get(new_session, 1)
    assert task is not None

    reset_task_session(new_session)
    task_after = _STORE.get(new_session, 1)
    assert task_after is None, "Task should be gone after session reset"
    print("  PASS")


async def run_all() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        await test_todo_write(tmpdir)
        await test_task_lifecycle(tmpdir)
        await test_session_reset(tmpdir)
    print("\n=== All tests passed ===")


if __name__ == "__main__":
    asyncio.run(run_all())
