"""Tool: Agent — spawn a sub-agent to handle a sub-task."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from harness.background_tasks import REGISTRY, BackgroundTask
from harness.tool_registry import Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    from backends.base import LLMBackend
    from harness.tool_registry import ToolRegistry

MAX_DEPTH = 3


class AgentTool(Tool):
    """
    Delegates a sub-task to a nested Orchestrator instance.

    The sub-agent gets a clean message history, inherits the parent's
    working directory and permission mode, and runs to completion before
    returning its final text response as the tool result.

    When run_in_background=true the sub-agent is launched as an asyncio.Task
    and the tool returns a task_id immediately so the parent can continue.
    """

    name = "Agent"
    description = (
        "Spawn a sub-agent to handle a focused sub-task. "
        "The sub-agent has access to all tools except Agent (no recursive nesting beyond depth 3). "
        "Use this for parallelisable or clearly separable work like exploration, "
        "research, or isolated refactors. "
        "Set run_in_background=true to launch the sub-agent asynchronously and continue "
        "working while it runs — retrieve its result later with TaskOutput. "
        "Describe the task clearly — the sub-agent starts with no context from the current conversation."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short label for this sub-agent (shown in the UI).",
            },
            "prompt": {
                "type": "string",
                "description": "The full task description for the sub-agent.",
            },
            "mode": {
                "type": "string",
                "enum": ["full", "read_only", "web_only"],
                "description": (
                    "Specialisation mode. "
                    "'full' (default): access to all tools. "
                    "'read_only': only Read, Glob, Grep, ListDir. "
                    "'web_only': only WebSearch, WebFetch, Playwright."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "If true, launch the sub-agent asynchronously and return a task_id "
                    "immediately without waiting for it to finish. "
                    "Use TaskOutput with that task_id to retrieve the result."
                ),
            },
        },
        "required": ["description", "prompt"],
    }

    def __init__(
        self,
        backend: "LLMBackend",
        registry: "ToolRegistry",
        emit_fn: Callable[[dict], None],
    ) -> None:
        self._backend = backend
        self._registry = registry
        self._emit_fn = emit_fn

    def is_read_only(self, input: dict) -> bool:
        return False  # sub-agents may write files

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        if ctx.depth >= MAX_DEPTH:
            return ToolResult.error(
                f"Maximum sub-agent nesting depth ({MAX_DEPTH}) reached."
            )

        from harness.subagent import run_subagent

        label: str = input.get("description", "sub-agent")
        prompt: str = input["prompt"]
        mode: str = input.get("mode", "full")
        run_in_background: bool = bool(input.get("run_in_background", False))

        # Map mode to tool allowlist
        tool_filter = None
        if mode == "read_only":
            tool_filter = ["Read", "Glob", "Grep", "ListDir"]
        elif mode == "web_only":
            tool_filter = ["WebSearch", "WebFetch", "Playwright"]

        if run_in_background:
            return self._launch_background(
                prompt, label, tool_filter, ctx
            )

        # Foreground (blocking) execution
        try:
            result = await run_subagent(
                task=prompt,
                backend=self._backend,
                registry=self._registry,
                working_directory=ctx.working_directory,
                permission_mode=ctx.permission_mode,
                emit_fn=self._emit_fn,
                depth=ctx.depth + 1,
                label=label,
                tool_filter=tool_filter,
            )
        except Exception as e:
            return ToolResult.error(f"Sub-agent failed: {e}")

        summary = f"[{label}] completed"
        return ToolResult.ok(result, summary)

    def _launch_background(
        self,
        prompt: str,
        label: str,
        tool_filter: list[str] | None,
        ctx: ToolContext,
    ) -> ToolResult:
        from harness.subagent import run_subagent
        import asyncio

        task_id = REGISTRY.new_id()
        bg = BackgroundTask(task_id=task_id, kind="agent", label=label)
        REGISTRY.register(bg)

        async def _run() -> None:
            try:
                result = await run_subagent(
                    task=prompt,
                    backend=self._backend,
                    registry=self._registry,
                    working_directory=ctx.working_directory,
                    permission_mode=ctx.permission_mode,
                    emit_fn=self._emit_fn,
                    depth=ctx.depth + 1,
                    label=label,
                    tool_filter=tool_filter,
                )
                bg.output = result
                bg.status = "completed"
            except asyncio.CancelledError:
                bg.status = "cancelled"
            except Exception as exc:
                bg.output = f"Sub-agent error: {exc}"
                bg.status = "failed"
            finally:
                import time
                bg.ended_at = time.monotonic()

        atask = asyncio.create_task(_run())
        bg._asyncio_task = atask

        return ToolResult.ok(
            f"Sub-agent launched in background.\ntask_id: {task_id}\n"
            f"Use TaskOutput with id={task_id} to retrieve the result when it completes.",
            f"bg:{task_id} agent — {label[:60]}",
        )
