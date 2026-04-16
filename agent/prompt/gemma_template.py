"""
Prompt Layer — Gemma Chat Template
=====================================
Renders the full prompt string in the Gemma instruction-tuning format.

Gemma 4 uses:
  <bos><start_of_turn>user
  {content}
  <end_of_turn>
  <start_of_turn>model
  {content}<end_of_turn>
  ...
  <start_of_turn>model

The system prompt and tools XML are prepended to the first user turn
(Gemma 4 does not have a dedicated system role).
"""

from __future__ import annotations

from harness.message import Message, TextBlock, ToolUseBlock, ToolResultBlock
import json

BOS = "<bos>"
START_USER = "<start_of_turn>user\n"
START_MODEL = "<start_of_turn>model\n"
END_TURN = "<end_of_turn>\n"


def _render_content_blocks(msg: Message) -> str:
    """Flatten message content blocks to a string."""
    parts: list[str] = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            parts.append(
                f"<tool_use>\n<name>{block.name}</name>\n"
                f"<input>\n{json.dumps(block.input, indent=2)}\n</input>\n</tool_use>"
            )
        elif isinstance(block, ToolResultBlock):
            status = "error" if block.is_error else "ok"
            parts.append(
                f"<tool_result id=\"{block.tool_use_id}\" status=\"{status}\">\n"
                f"{block.content}\n</tool_result>"
            )
    return "\n".join(parts)


def render_prompt(
    messages: list[Message],
    system_prompt: str,
    tools_xml: str,
) -> str:
    """
    Render the full prompt for the model.

    Parameters
    ----------
    messages:
        Conversation history (role=user|assistant only; system messages
        are handled separately).
    system_prompt:
        Built by ``build_system_prompt()``.
    tools_xml:
        Built by ``render_tools_xml()``.
    """
    parts: list[str] = [BOS]

    for i, msg in enumerate(messages):
        content = _render_content_blocks(msg)
        if msg.role == "user":
            # Inject system prompt + tools into the FIRST user turn only
            if i == 0:
                preamble = f"{system_prompt}\n\n{tools_xml}\n\n"
                content = preamble + content
            parts.append(START_USER + content + END_TURN)
        elif msg.role == "assistant":
            parts.append(START_MODEL + content + END_TURN)

    # Open the model turn for the next generation
    parts.append(START_MODEL)

    return "".join(parts)
