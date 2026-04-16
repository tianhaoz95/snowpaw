"""
Agent Layer — Message Types
============================
Mirrors the Anthropic API message format used by claude-code (Tool.ts,
types/message.ts) but as plain Python dataclasses — no external schema
dependency.

A conversation is a list[Message].  Each Message has a role and a list
of content blocks.  Blocks are one of:

  TextBlock       — plain text (assistant narration or user input)
  ToolUseBlock    — the model wants to call a tool
  ToolResultBlock — the result of a tool call
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Union


Role = Literal["system", "user", "assistant"]


# ── Content Blocks ────────────────────────────────────────────────────────────

@dataclass
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""

    def to_dict(self) -> dict:
        return {"type": self.type, "text": self.text}


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str = field(default_factory=lambda: f"tu_{uuid.uuid4().hex[:12]}")
    type: Literal["tool_use"] = "tool_use"

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
        }


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


# ── Message ───────────────────────────────────────────────────────────────────

@dataclass
class Message:
    role: Role
    content: list[ContentBlock] = field(default_factory=list)

    # ── Convenience constructors ───────────────────────────────────────────────

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(role="user", content=[TextBlock(text=text)])

    @classmethod
    def assistant_text(cls, text: str) -> "Message":
        return cls(role="assistant", content=[TextBlock(text=text)])

    @classmethod
    def tool_result(cls, tool_use_id: str, content: str, is_error: bool = False) -> "Message":
        return cls(
            role="user",
            content=[ToolResultBlock(
                tool_use_id=tool_use_id,
                content=content,
                is_error=is_error,
            )],
        )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": [b.to_dict() for b in self.content],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        blocks: list[ContentBlock] = []
        for b in d.get("content", []):
            t = b.get("type")
            if t == "text":
                blocks.append(TextBlock(text=b["text"]))
            elif t == "tool_use":
                blocks.append(ToolUseBlock(
                    id=b["id"], name=b["name"], input=b["input"]
                ))
            elif t == "tool_result":
                blocks.append(ToolResultBlock(
                    tool_use_id=b["tool_use_id"],
                    content=b["content"],
                    is_error=b.get("is_error", False),
                ))
        return cls(role=d["role"], content=blocks)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def text_content(self) -> str:
        """Concatenate all TextBlock texts."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def char_count(self) -> int:
        """Rough character count for context budget estimation."""
        return sum(len(b.text if isinstance(b, TextBlock) else
                       b.content if isinstance(b, ToolResultBlock) else
                       str(b.input))
                   for b in self.content)
