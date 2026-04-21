"""
Harness — Orchestrator
=======================
The main agent loop.  Mirrors the QueryEngine + runAgent pattern from
claude-code but adapted for local LLM JSON-based tool calling (Gap 9).

Loop
----
1. Append user message to history.
2. Compact history if near context limit.
3. Render full prompt (Gemma template).
4. Stream tokens from the LLM backend.
5. Parse tool call blocks from the streamed text.
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
import time
import uuid
import os
from typing import Callable

from backends.base import GenerateParams, LLMBackend
from prompt.model_template import render_prompt
from prompt.system_prompt import build_system_prompt, build_session_context
from prompt.tools_xml import render_tools_json
from .context_manager import compact, should_compact, truncate_tool_result
from .message import Message, TextBlock, ToolResultBlock, ToolUseBlock
from .permissions import PermissionDenied, PermissionManager, PermissionMode
from .tool_registry import ToolContext, ToolRegistry

log = logging.getLogger(__name__)



class Orchestrator:
    """
    Coordinates the conversation, tool execution, and UI events.
    """

    def __init__(
        self,
        backend: LLMBackend,
        registry: ToolRegistry,
        system_prompt: str,
        working_directory: str,
        permission_mode: PermissionMode = PermissionMode.ASK,
        emit_fn: Callable[[dict], None] | None = None,
        context_size: int = 8192,
        session_id: str = "",
        depth: int = 0,
        network_enabled: bool = False,
    ) -> None:
        self._backend = backend
        self._registry = registry
        self._system_prompt = system_prompt
        self._working_directory = working_directory
        self._permission_mode = permission_mode
        self._emit = emit_fn or (lambda _: None)
        self._context_size = context_size
        self._session_id = session_id
        self._depth = depth
        self._params = GenerateParams(temperature=0.0)  # default for coding
        self._network_enabled = network_enabled

        self._messages: list[Message] = []
        self._permission_manager = PermissionManager()
        self._interrupted = False

    def _persist_message(self, msg: Message) -> None:
        """Append a message to the session log on disk (Gap 13)."""
        if not self._session_id or self._depth > 0:
            return  # Don't persist sub-agent sessions or if no ID
        
        path = os.path.join(self._working_directory, ".cyberpaw", "sessions", f"{self._session_id}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg.to_dict()) + "\n")
        except Exception as e:
            log.warning("Failed to persist message to %s: %s", path, e)

    def _append_message(self, msg: Message) -> None:
        """Add a message to history and persist to disk."""
        self._messages.append(msg)
        self._persist_message(msg)

    # ── Public API ─────────────────────────────────────────────────────────────

    def interrupt(self) -> None:
        """Signal the running loop to stop after the current tool completes."""
        self._interrupted = True

    def set_working_directory(self, path: str) -> None:
        self._working_directory = path
        self._system_prompt = build_system_prompt()

    def resolve_permission(self, request_id: str, approved: bool) -> None:
        """Called when a tool_ack arrives from the frontend."""
        self._permission_manager.resolve(request_id, approved)

    async def handle_input(self, text: str) -> None:
        """Process a user message and run the agent loop."""
        self._interrupted = False
        
        # Inject session context into the first user message for KV caching
        # of the system prompt prefix.
        if not self._messages:
            context = build_session_context(self._working_directory)
            text = f"{context}\n\nUser: {text}"
            
        self._append_message(Message.user(text))
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
        # Inject session context into the first user message
        if not self._messages:
            context = build_session_context(self._working_directory)
            task = f"{context}\n\nUser: {task}"
            
        self._append_message(Message.user(task))
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

    def load_session(self, session_id: str) -> bool:
        """
        Reconstruct conversation history from a persisted session log (Gap 13).
        Returns True if successful.
        """
        path = os.path.join(self._working_directory, ".cyberpaw", "sessions", f"{session_id}.jsonl")
        if not os.path.isfile(path):
            return False
        
        try:
            messages = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        messages.append(Message.from_dict(json.loads(line)))
            self._messages = messages
            self._session_id = session_id
            log.info("Loaded %d messages from session %s", len(messages), session_id)
            return True
        except Exception as e:
            log.warning("Failed to load session from %s: %s", path, e)
            return False

    # ── Internal loop ─────────────────────────────────────────────────────────

    async def _agent_loop(self) -> None:
        tools_schema = render_tools_json(self._registry)

        # Derive stop sequences from the model's own EOS vocabulary so that
        # every model family (Gemma, Qwen, …) stops on its correct token.
        backend_eos = self._backend.eos_strings()
        if backend_eos:
            self._params.stop_sequences = backend_eos

        # Prime the KV cache with the static system prefix.
        from harness.message import Message as _Msg
        _primer = render_prompt([_Msg.user("")], self._system_prompt, tools_schema, self._backend)
        await self._backend.prime_cache(_primer)

        # Loop-detection state: track (tool, input_hash, error_summary) tuples.
        # A "strike" is one repeated failing call; three strikes triggers an intervention.
        _recent_calls: list[tuple[str, str, str]] = []  # (tool, input_hash, result_summary)
        _LOOP_WINDOW = 4    # look back this many calls
        _LOOP_STRIKES = 2   # how many identical failing calls before intervening

        turn = 0
        while True:
            turn += 1
            if self._interrupted:
                self._emit({"type": "token", "text": "\n[interrupted]\n"})
                break

            self._emit({"type": "status", "phase": "thinking"})

            # Compact if near context limit
            if should_compact(
                self._messages,
                self._context_size,
                count_tokens_fn=self._backend.count_tokens,
            ):
                # Pass session_id and working_directory for disk persistence (Gap 2)
                self._messages, n = compact(
                    self._messages,
                    session_id=self._session_id,
                    working_directory=self._working_directory
                )
                if n:
                    self._emit({
                        "type": "system",
                        "text": f"[compacted {n} tool results to save context]",
                    })

            # Render prompt and call the LLM
            prompt = render_prompt(self._messages, self._system_prompt, tools_schema, self._backend)
            response_text = await self._stream_llm(prompt)

            # Parse tool calls from the response
            tool_uses = _parse_tool_uses(response_text)

            # Build assistant message (text + tool_use blocks)
            # Strip <thought> blocks from the message history (Gap 7)
            clean_response = _strip_thoughts(response_text)
            
            assistant_content = []
            # Text before the first tool call (in the cleaned response)
            pre_text = _text_before_first_tool(clean_response)
            if pre_text.strip():
                assistant_content.append(TextBlock(text=pre_text))
            for tu in tool_uses:
                assistant_content.append(tu)

            if assistant_content:
                self._append_message(
                    Message(role="assistant", content=assistant_content)
                )

            # Detect failed tool calls — covers both JSON and XML formats.
            # Only check the thought-stripped response to avoid false positives
            # from <tool_use> examples inside <thought> blocks.
            _looks_like_tool_call = (
                '{"tool":' in clean_response
                or '"tool":' in clean_response
                or '<tool_use>' in clean_response.lower()
            )
            if not tool_uses and _looks_like_tool_call:
                error_msg = (
                    "Your tool call was malformed. Ensure you emit a valid "
                    'JSON object on a single line starting with {"tool": "ToolName", "input": {...}}.'
                )
                self._append_message(Message.user(error_msg))
                self._emit({
                    "type": "token",
                    "text": "\n[error: malformed tool call, retrying...]\n",
                })
                continue

            if not tool_uses:
                # Only break if the model produced actual visible text — that
                # means it's genuinely done. If the response is empty or was
                # entirely <thought> blocks (stripped away), treat it as a
                # stalled generation and retry rather than halting the task.
                visible_text = clean_response.strip()
                if not visible_text:
                    if not response_text.strip():
                        self._emit({
                            "type": "token",
                            "text": "\n[model returned an empty response — retrying...]\n",
                        })
                    else:
                        # Response had only <thought> content — model is thinking
                        # but didn't emit a tool call or final answer. Nudge it.
                        self._emit({
                            "type": "token",
                            "text": "\n[model produced only internal thoughts — nudging...]\n",
                        })
                    self._append_message(Message.user(
                        "Please continue. Either call a tool to make progress, "
                        "or write your final answer if the task is complete."
                    ))
                    continue
                break

            # Execute tool calls and collect results
            result_blocks = await self._execute_tool_uses(tool_uses)

            # ── Loop detection ────────────────────────────────────────────────
            # Record (tool, input_hash, is_error, result_prefix) for each call.
            # If the same failing (tool, input) pair repeats >= _LOOP_STRIKES times
            # in the last _LOOP_WINDOW entries, inject an intervention message.
            from collections import Counter
            for tu, rb in zip(tool_uses, result_blocks):
                input_hash = str(sorted(tu.input.items()))[:120]
                _recent_calls.append((tu.name, input_hash, rb.is_error, rb.content[:120]))

            if len(_recent_calls) > _LOOP_WINDOW * 2:
                _recent_calls = _recent_calls[-_LOOP_WINDOW * 2:]

            window = _recent_calls[-_LOOP_WINDOW:]
            # Only count failing calls (is_error=True) for loop detection
            failing_sigs = Counter(
                (t, i) for t, i, is_err, _ in window if is_err
            )
            if failing_sigs:
                most_common_sig, count = failing_sigs.most_common(1)[0]
                if count >= _LOOP_STRIKES:
                    loop_tool, _ = most_common_sig
                    loop_error = next(
                        r for t, i, is_err, r in window
                        if (t, i) == most_common_sig and is_err
                    )
                    intervention = (
                        f"You have called {loop_tool} with the same input {count} times "
                        f"and received the same error each time:\n  {loop_error}\n\n"
                        "This approach is not working. You MUST try something different:\n"
                        "- If a file edit keeps failing, Read the file first to see its actual current content.\n"
                        "- If a shell command keeps failing, read the full error output and try a different approach.\n"
                        "- If you are genuinely stuck, stop and explain to the user what you have tried "
                        "and what is blocking you.\n"
                        "Do NOT repeat the same failing call again."
                    )
                    result_blocks.append(ToolResultBlock(
                        tool_use_id=f"loop_intervention_{turn}",
                        content=intervention,
                        is_error=True,
                    ))
                    self._emit({
                        "type": "system",
                        "text": f"[loop detected: {loop_tool} failed {count}x in a row — intervening]",
                    })
                    _recent_calls.clear()

            # Append tool results as a user message
            self._append_message(
                Message(role="user", content=result_blocks)
            )


    async def _stream_llm(self, prompt: str) -> str:
        """Stream tokens from the LLM and emit them; return full response."""
        full = ""
        # Buffer until we hit a JSON tool call or <thought> open tag to avoid partial-tag display.
        # The tail kept in the buffer must be at least as long as the longest
        # stop sequence so that a partial stop token is never emitted mid-stream.
        # "<end_of_turn>" is 13 chars; use 16 to cover any variant.
        _TAIL = 16
        buffer = ""
        in_suppressed_block = False
        _close_tag: str | None = None
        token_count = 0
        t_start = time.monotonic()

        async for token in self._backend.generate(prompt, self._params):
            if self._interrupted:
                break

            full += token
            buffer += token
            token_count += 1

            while buffer:
                if not in_suppressed_block:
                    thought_idx = buffer.find("<thought>")
                    json_idx    = buffer.find('{"tool":')
                    xml_idx     = buffer.lower().find("<tool_use>")

                    # Pick whichever suppression trigger comes first
                    candidates = [
                        (thought_idx, "<thought>",  "</thought>"),
                        (json_idx,    '{"tool":',   None),        # ends at closing brace + newline
                        (xml_idx,     "<tool_use>", "</tool_use>"),
                    ]
                    best = min(
                        ((idx, open_tag, close_tag) for idx, open_tag, close_tag in candidates if idx != -1),
                        key=lambda t: t[0],
                        default=None,
                    )

                    if best is not None:
                        found_idx, open_tag, close_tag = best
                        pre = buffer[:found_idx]
                        if pre:
                            self._emit({"type": "token", "text": _strip_stop(pre, self._params.stop_sequences)})
                        buffer = buffer[found_idx:]
                        in_suppressed_block = True
                        _close_tag = close_tag
                    elif len(buffer) > _TAIL * 2:
                        safe = buffer[:-_TAIL]
                        self._emit({"type": "token", "text": safe})
                        buffer = buffer[-_TAIL:]
                        break
                    else:
                        break
                else:
                    # Find the end of the current suppressed block
                    found_end_idx = -1
                    tag_len = 0

                    if _close_tag is not None:
                        # <thought> or <tool_use> — wait for explicit close tag
                        end = buffer.lower().find(_close_tag.lower())
                        if end != -1:
                            found_end_idx = end
                            tag_len = len(_close_tag)
                    else:
                        # JSON {"tool": — find the closing brace of the outermost object.
                        # We track brace depth to handle multi-line JSON correctly.
                        start = buffer.find('{"tool":')
                        if start != -1:
                            depth = 0
                            in_str = False
                            escape_next = False
                            for ci, ch in enumerate(buffer[start:], start):
                                if escape_next:
                                    escape_next = False
                                    continue
                                if ch == "\\" and in_str:
                                    escape_next = True
                                    continue
                                if ch == '"':
                                    in_str = not in_str
                                    continue
                                if in_str:
                                    continue
                                if ch == "{":
                                    depth += 1
                                elif ch == "}":
                                    depth -= 1
                                    if depth == 0:
                                        found_end_idx = ci
                                        tag_len = 1  # consume the closing brace itself
                                        break

                    if found_end_idx != -1:
                        in_suppressed_block = False
                        _close_tag = None
                        buffer = buffer[found_end_idx + tag_len:]
                    else:
                        break  # Still in suppressed block, wait for next token

        # Flush remaining buffer — always emit, even if we ended mid-suppressed-block.
        # Discarding it would make the response look empty and cause a premature halt.
        if buffer:
            self._emit({"type": "token", "text": _strip_stop(buffer, self._params.stop_sequences)})

        full = _strip_stop(full, self._params.stop_sequences)

        elapsed = time.monotonic() - t_start
        tps = token_count / elapsed if elapsed > 0 else 0.0
        self._emit({
            "type": "generation_stats",
            "tokens": token_count,
            "elapsed_ms": round(elapsed * 1000),
            "tokens_per_sec": round(tps, 1),
        })

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
    """
    Extract all tool calls from LLM output, with fallbacks for fragile
    small-model output.

    Returns a list of parsed tool calls.  When a tool call is detected but
    JSON parsing fails, the function returns an empty list;
    the malformed-tool-call heuristic in _agent_loop (which checks for
    '{"tool":' in the raw text) will then fire and ask the model
    to retry with correct formatting.
    """
    results: list[ToolUseBlock] = []
    seen_ids: set[str] = set()

    def add_result(name: str, input_data: dict):
        if not name:
            return
        # Use a stable hash of the call for deduplication
        call_id = f"{name}:{json.dumps(input_data, sort_keys=True)}"
        if call_id not in seen_ids:
            results.append(ToolUseBlock(name=name, input=input_data))
            seen_ids.add(call_id)

    # 1. Primary: single-line JSON  {"tool": ...} or {"name": ...}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('{"tool":') or line.startswith('{"name":'):
            try:
                data = json.loads(line)
                name = data.get("tool") or data.get("name")
                input_data = data.get("input") if "input" in data else {k: v for k, v in data.items() if k not in ["tool", "name"]}
                if name and isinstance(input_data, dict):
                    add_result(name, input_data)
            except json.JSONDecodeError:
                log.debug("JSON parse failed for line: %s", line[:120])

    # 2. Multi-line JSON — brace-depth scan for {"tool": ... } spanning lines.
    # Handles models that pretty-print their tool calls.
    search_start = 0
    while True:
        idx = text.find('{"tool":', search_start)
        if idx == -1:
            idx = text.find('{"name":', search_start)
        if idx == -1:
            break
        depth = 0
        in_str = False
        escape_next = False
        end_idx = -1
        for ci, ch in enumerate(text[idx:], idx):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_str:
                escape_next = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = ci
                    break
        if end_idx != -1:
            candidate = text[idx:end_idx + 1]
            if "\n" in candidate:  # only needed for multi-line; single-line already handled above
                try:
                    data = json.loads(candidate)
                    name = data.get("tool") or data.get("name")
                    input_data = data.get("input") if "input" in data else {k: v for k, v in data.items() if k not in ["tool", "name"]}
                    if name and isinstance(input_data, dict):
                        add_result(name, input_data)
                except json.JSONDecodeError:
                    pass
            search_start = end_idx + 1
        else:
            break

    # 3. Fallback: XML  <tool_use>...</tool_use>
    xml_re = re.compile(
        r"<tool_use>.*?<name>(.*?)</name>.*?<input>(.*?)</input>.*?(?:</tool_use>|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in xml_re.finditer(text):
        name = m.group(1).strip()
        raw_input = m.group(2).strip()
        try:
            add_result(name, json.loads(raw_input))
        except json.JSONDecodeError:
            pass

    return results


def _text_before_first_tool(text: str) -> str:
    """Return the text portion before the first tool call."""
    idx = text.find('{"tool":')
    if idx == -1:
        # Check XML fallback
        idx = text.find("<tool_use>")
        
    if idx == -1:
        return text
    return text[:idx]


def _strip_thoughts(text: str) -> str:
    """Remove <thought>...</thought> blocks from the text (Gap 7)."""
    return re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


def _strip_stop(text: str, stop_sequences: list[str]) -> str:
    """
    Remove any stop sequence that appears at the tail of *text*.

    llama-cpp-python (and some other backends) include the matched stop string
    in the last yielded token.  Stripping it here prevents chat-template tokens
    like <end_of_turn> or </start_of_turn> from leaking into the displayed
    output or being passed to _parse_tool_uses.
    """
    for seq in stop_sequences:
        if text.endswith(seq):
            return text[: -len(seq)]
        # Also strip if the stop token is followed only by whitespace/newlines
        stripped = text.rstrip()
        if stripped.endswith(seq):
            return stripped[: -len(seq)]
    return text
