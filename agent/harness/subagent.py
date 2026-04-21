"""
Agent Layer — Sub-Agent Runner
================================
Implements the ``Agent`` tool's backend: spawns a nested Orchestrator
with a clean message slate and a sub-task prompt, runs it to completion,
and returns the final text response.

Mirrors claude-code's ``runAgent.ts`` / ``InProcessBackend`` pattern but
as an asyncio coroutine (no OS processes).

Max nesting depth: 3 (enforced by the Agent tool itself).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from .message import Message
from .permissions import PermissionMode

if TYPE_CHECKING:
    from .orchestrator import Orchestrator
    from backends.base import LLMBackend
    from .tool_registry import ToolRegistry

log = logging.getLogger(__name__)


async def run_subagent(
    task: str,
    backend: "LLMBackend",
    registry: "ToolRegistry",
    working_directory: str,
    permission_mode: PermissionMode,
    emit_fn: Callable[[dict], None],
    depth: int,
    label: str,
    tool_filter: list[str] | None = None,
) -> str:
    """
    Run a sub-agent to completion and return its final text response.

    Parameters
    ----------
    task:
        The sub-task description (becomes the first user message).
    backend:
        Shared LLM backend (model is already loaded).
    registry:
        Tool registry — sub-agents get the same tools as the parent
        minus the Agent tool itself (to prevent circular delegation).
    working_directory:
        Inherited from parent.
    permission_mode:
        Inherited from parent.
    emit_fn:
        Output emitter — tokens and tool events are prefixed with the
        agent label so the frontend can distinguish them.
    depth:
        Current nesting depth (parent's depth + 1).
    label:
        Human-readable label for this sub-agent, e.g. "explore-agent".
    tool_filter:
        Optional list of tool names that the sub-agent is allowed to use.
        If None, all tools except 'Agent' are available.
    """
    # Import here to avoid circular dependency at module load time
    from .orchestrator import Orchestrator
    from prompt.system_prompt import build_system_prompt

    # Build a prefixed emitter so the frontend can distinguish sub-agent output
    def prefixed_emit(event: dict) -> None:
        event = dict(event)
        event["agent_label"] = label
        emit_fn(event)

    system_prompt = build_system_prompt()

    # Remove the Agent tool from the sub-registry to prevent infinite nesting
    from .tool_registry import ToolRegistry
    sub_registry = ToolRegistry()
    for tool in registry.all():
        if tool.name == "Agent":
            continue
        if tool_filter is not None and tool.name not in tool_filter:
            continue
        sub_registry.register(tool)

    orchestrator = Orchestrator(
        backend=backend,
        registry=sub_registry,
        system_prompt=system_prompt,
        working_directory=working_directory,
        permission_mode=permission_mode,
        emit_fn=prefixed_emit,
        depth=depth,
    )

    final_text = await orchestrator.run_task(task)
    log.info("Sub-agent '%s' finished: %d chars output", label, len(final_text))
    return final_text
