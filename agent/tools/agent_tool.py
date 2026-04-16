"""Tool: Agent — spawn a sub-agent to handle a sub-task."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

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

    Mirrors claude-code's AgentTool / InProcessBackend pattern.
    """

    name = "Agent"
    description = (
        "Spawn a sub-agent to handle a focused sub-task. "
        "The sub-agent has access to all tools except Agent (no recursive nesting beyond depth 3). "
        "Use this for parallelisable or clearly separable work like exploration, "
        "research, or isolated refactors. "
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
            "subagent_type": {
                "type": "string",
                "description": (
                    "Optional specialisation hint. "
                    "Currently unused — all sub-agents use the same model."
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
        from harness.permissions import PermissionMode

        label: str = input.get("description", "sub-agent")
        prompt: str = input["prompt"]

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
            )
        except Exception as e:
            return ToolResult.error(f"Sub-agent failed: {e}")

        summary = f"[{label}] completed"
        return ToolResult.ok(result, summary)
