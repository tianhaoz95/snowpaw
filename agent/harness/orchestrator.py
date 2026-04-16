"""
Harness — Orchestrator
=======================
The main agent loop.  Mirrors the QueryEngine + runAgent pattern from
claude-code but adapted for local LLM XML-based tool calling.

Loop
----
1. Append user message to history.
2. Compact history if near context limit.
3. Render full prompt (Gemma template).
4. Stream tokens from the LLM backend.
5. Parse <tool_use> blocks from the streamed text.
6. For each tool call:
   a. Check permissions (may suspend and wait for user approval).
   b. Execute the tool.
   c. Append ToolResultBlock to history.
7. If any tool calls were made → goto 2.
8. Emit ``status: idle`` and return the final text response.

The orchestrator is also used by sub-agents (via subagent.py) with a
clean message history and a sub-task prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Callable

from backends.base import GenerateParams, LLMBackend
from prompt.gemma_template import render_prompt
from prompt.system_prompt import build_system_prompt
from prompt.tools_xml import render_tools_xml
from .context_manager import compact, should_compact, truncate_tool_result
from .message import Message, TextBlock, ToolResultBlock, ToolUseBlock
from .permissions import PermissionDenied, PermissionManager, PermissionMode
from .tool_registry import ToolContext, ToolRegistry

log = logging.getLogger(__name__)

MAX_TURNS = 40  # hard cap on tool-call iterations per user message

# Regex to extract <tool_use> blocks from streamed LLM output.
# The closing </tool_use> is made optional: the model may stop generating
# exactly at the stop sequence boundary, leaving the tag absent.
_TOOL_USE_RE = re.compile(
    r"<tool_use>\s*<name>(.*?)</name>\s*<input>(.*?)</input>\s*(?:</tool_use>|$)",
    re.DOTALL,
)


class Orchestrator:
    """
    Stateful agent loop for a single conversation session.

    Parameters
    ----------
    backend:
        Loaded LLM backend (model must be ready before first call).
    registry:
        Tool registry with all available tools.
    system_prompt:
        Pre-built system prompt string.
    working_directory:
        Absolute path to the user's project directory.
    permission_mode:
        Controls which tool calls require user approval.
    emit_fn:
        Callable that accepts a dict and sends it as an NDJSON line to
        the Tauri frontend.  All agent output goes through this.
    depth:
        Nesting depth (0 = root agent, 1+ = sub-agents).
    generate_params:
        Inference hyperparameters.
    context_size:
        Model context window in tokens (used for compaction decisions).
    """

    def __init__(
        self,
        backend: LLMBackend,
        registry: ToolRegistry,
        system_prompt: str,
        working_directory: str,
        permission_mode: PermissionMode,
        emit_fn: Callable[[dict], None],
        depth: int = 0,
        generate_params: GenerateParams | None = None,
        context_size: int = 8192,
        session_id: str = "",
        network_enabled: bool = False,
    ) -> None:
        self._backend = backend
        self._registry = registry
        self._system_prompt = system_prompt
        self._working_directory = working_directory
        self._permission_mode = permission_mode
        self._emit = emit_fn
        self._depth = depth
        self._params = generate_params or GenerateParams()
        self._context_size = context_size
        self._session_id = session_id
        self._network_enabled = network_enabled

        self._messages: list[Message] = []
        self._permission_manager = PermissionManager()
        self._interrupted = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        """Signal the running loop to stop after the current tool completes."""
        self._interrupted = True

    def set_working_directory(self, path: str) -> None:
        self._working_directory = path
        self._system_prompt = build_system_prompt(working_directory=path)

    def resolve_permission(self, request_id: str, approved: bool) -> None:
        """Called when a tool_ack arrives from the frontend."""
        self._permission_manager.resolve(request_id, approved)

    async def handle_input(self, text: str) -> None:
        """Process a user message and run the agent loop."""
        self._interrupted = False
        self._messages.append(Message.user(text))
        self._emit({"type": "status", "phase": "thinking"})
        try:
            await self._agent_loop()
        except asyncio.CancelledError:
            self._emit({"type": "error", "message": "Cancelled"})
        except Exception as exc:
            log.exception("Agent loop error")
            self._emit({"type": "error", "message": str(exc)})
        finally:
            self._emit({"type": "status", "phase": "idle"})

    async def run_task(self, task: str) -> str:
        """
        Run a single task to completion (used by sub-agents).
        Returns the final assistant text response.
        """
        self._messages.append(Message.user(task))
        await self._agent_loop()
        # Return the last assistant text
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg.text_content()
        return ""

    def reset(self) -> None:
        """Clear conversation history."""
        self._messages = []
        self._interrupted = False

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _agent_loop(self) -> None:
        tools_xml = render_tools_xml(self._registry)

        for turn in range(MAX_TURNS):
            if self._interrupted:
                self._emit({"type": "token", "text": "\n[interrupted]\n"})
                break

            # Compact if near context limit
            if should_compact(self._messages, self._context_size):
                self._messages, n = compact(self._messages)
                if n:
                    self._emit({
                        "type": "system",
                        "text": f"[compacted {n} tool results to save context]",
                    })

            # Render prompt and call the LLM
            prompt = render_prompt(self._messages, self._system_prompt, tools_xml)
            response_text = await self._stream_llm(prompt)

            # Parse tool calls from the response
            tool_uses = _parse_tool_uses(response_text)

            # Build assistant message (text + tool_use blocks)
            assistant_content = []
            # Text before the first tool_use tag
            pre_text = _text_before_first_tool(response_text)
            if pre_text.strip():
                assistant_content.append(TextBlock(text=pre_text))
            for tu in tool_uses:
                assistant_content.append(tu)

            if assistant_content:
                self._messages.append(
                    Message(role="assistant", content=assistant_content)
                )

            if not tool_uses:
                # No tool calls — the model is done for this turn
                break

            # Execute tool calls and collect results
            result_blocks = await self._execute_tool_uses(tool_uses)

            # Append tool results as a user message
            self._messages.append(
                Message(role="user", content=result_blocks)
            )

        else:
            self._emit({
                "type": "system",
                "text": f"[reached maximum turn limit of {MAX_TURNS}]",
            })

    async def _stream_llm(self, prompt: str) -> str:
        """Stream tokens from the LLM and emit them; return full response."""
        full = ""
        # Buffer until we hit a <tool_use> open tag to avoid partial-tag display
        buffer = ""
        in_tool_block = False

        async for token in self._backend.generate(prompt, self._params):
            if self._interrupted:
                break

            full += token
            buffer += token

            if not in_tool_block:
                if "<tool_use>" in buffer:
                    # Emit everything up to the tag, then suppress the rest
                    pre, _, rest = buffer.partition("<tool_use>")
                    if pre:
                        self._emit({"type": "token", "text": pre})
                    buffer = "<tool_use>" + rest
                    in_tool_block = True
                elif len(buffer) > 20:
                    # Safe to emit — no partial tag at the end
                    safe = buffer[:-10]
                    self._emit({"type": "token", "text": safe})
                    buffer = buffer[-10:]
            else:
                if "</tool_use>" in buffer:
                    in_tool_block = False
                    # Emit what comes after the closing tag
                    _, _, after = buffer.partition("</tool_use>")
                    buffer = after

        # Flush remaining buffer
        if buffer and not in_tool_block:
            self._emit({"type": "token", "text": buffer})

        return full

    async def _execute_tool_uses(
        self, tool_uses: list[ToolUseBlock]
    ) -> list[ToolResultBlock]:
        """Execute a list of tool calls, respecting permissions."""
        result_blocks: list[ToolResultBlock] = []

        for tu in tool_uses:
            if self._interrupted:
                result_blocks.append(ToolResultBlock(
                    tool_use_id=tu.id,
                    content="Interrupted by user.",
                    is_error=True,
                ))
                continue

            tool = self._registry.get(tu.name)
            if tool is None:
                self._emit({
                    "type": "tool_end",
                    "tool": tu.name,
                    "summary": f"Unknown tool: {tu.name}",
                    "is_error": True,
                })
                result_blocks.append(ToolResultBlock(
                    tool_use_id=tu.id,
                    content=f"Tool '{tu.name}' is not available.",
                    is_error=True,
                ))
                continue

            # Permission check
            if tool.requires_permission(tu.input, self._permission_mode):
                request_id = f"perm_{uuid.uuid4().hex[:8]}"
                approved = await self._permission_manager.request_permission(
                    request_id=request_id,
                    emit_fn=self._emit,
                    tool_name=tu.name,
                    tool_input=tu.input,
                )
                if not approved:
                    self._emit({
                        "type": "tool_end",
                        "tool": tu.name,
                        "summary": "Denied by user",
                        "is_error": True,
                    })
                    result_blocks.append(ToolResultBlock(
                        tool_use_id=tu.id,
                        content="Tool call denied by user.",
                        is_error=True,
                    ))
                    continue

            # Emit tool_start
            self._emit({
                "type": "tool_start",
                "id": tu.id,
                "tool": tu.name,
                "input": tu.input,
            })
            self._emit({"type": "status", "phase": "tool_running", "tool": tu.name})

            ctx = ToolContext(
                working_directory=self._working_directory,
                permission_mode=self._permission_mode,
                depth=self._depth,
                session_id=self._session_id,
                network_enabled=self._network_enabled,
            )

            try:
                result = await tool.call(tu.input, ctx)
            except Exception as exc:
                log.exception("Tool %s raised an exception", tu.name)
                result_content = f"Tool error: {exc}"
                is_error = True
                summary = f"Error in {tu.name}"
            else:
                result_content = truncate_tool_result(result.output)
                is_error = result.is_error
                summary = result.summary

            self._emit({
                "type": "tool_end",
                "id": tu.id,
                "tool": tu.name,
                "summary": summary,
                "is_error": is_error,
            })
            self._emit({"type": "status", "phase": "thinking"})

            result_blocks.append(ToolResultBlock(
                tool_use_id=tu.id,
                content=result_content,
                is_error=is_error,
            ))

        return result_blocks


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_tool_uses(text: str) -> list[ToolUseBlock]:
    """Extract all <tool_use> blocks from LLM output."""
    results: list[ToolUseBlock] = []
    for m in _TOOL_USE_RE.finditer(text):
        name = m.group(1).strip()
        raw_input = m.group(2).strip()
        try:
            parsed_input = json.loads(raw_input)
        except json.JSONDecodeError:
            log.warning("Could not parse tool input JSON for %s: %r", name, raw_input)
            parsed_input = {"raw": raw_input}
        results.append(ToolUseBlock(name=name, input=parsed_input))
    return results


def _text_before_first_tool(text: str) -> str:
    """Return the text portion before the first <tool_use> tag."""
    idx = text.find("<tool_use>")
    if idx == -1:
        return text
    return text[:idx]
