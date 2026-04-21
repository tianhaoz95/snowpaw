"""
Agent Layer — Tool Registry
============================
Defines the Tool ABC and a simple registry that maps tool names to
instances.  All concrete tools (Read, Write, Edit, …) live in
``agent/tools/`` and register themselves here.

Inspired by claude-code's Tool.ts / buildTool pattern but adapted for
Python and local-LLM XML-based tool calling.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .permissions import PermissionMode

log = logging.getLogger(__name__)


# ── Tool Context ──────────────────────────────────────────────────────────────

@dataclass
class ToolContext:
    """Runtime context passed to every tool call."""
    working_directory: str
    permission_mode: "PermissionMode"
    depth: int = 0          # agent nesting depth (0 = root)
    session_id: str = ""
    network_enabled: bool = False  # opt-in; off by default


# ── Tool Result ───────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    output: str
    is_error: bool = False
    summary: str = ""       # short human-readable summary for the UI

    @classmethod
    def ok(cls, output: str, summary: str = "") -> "ToolResult":
        return cls(output=output, is_error=False, summary=summary or output[:80])

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(output=message, is_error=True, summary=f"Error: {message[:60]}")


# ── Tool ABC ──────────────────────────────────────────────────────────────────

class Tool(abc.ABC):
    """
    Abstract base for all agent tools.

    Subclasses must set ``name``, ``description``, and ``input_schema``
    as class attributes, and implement ``call()``.
    """

    # ── Class-level metadata (set by subclasses) ───────────────────────────────
    name: str
    description: str
    input_schema: dict[str, Any]   # JSON Schema object

    # ── Abstract interface ─────────────────────────────────────────────────────

    @abc.abstractmethod
    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        """Execute the tool and return a ToolResult."""

    # ── Permission helpers ────────────────────────────────────────────────────

    def is_read_only(self, input: dict) -> bool:
        """Return True if this tool call makes no persistent changes."""
        return False

    def requires_permission(self, input: dict, mode: "PermissionMode") -> bool:
        """
        Return True if the harness should pause and ask the user before
        running this tool call in the given permission mode.
        """
        from .permissions import PermissionMode
        if mode == PermissionMode.AUTO_ALL:
            return False
        if mode == PermissionMode.AUTO_READ and self.is_read_only(input):
            return False
        return not self.is_read_only(input)

    # ── Schema rendering ──────────────────────────────────────────────────────

    def to_xml(self) -> str:
        """Render this tool's description as an XML block for the system prompt."""
        import json
        # Use compact (non-indented) JSON — indented JSON confuses small models
        # and causes them to emit garbled or empty output.
        schema_str = json.dumps(self.input_schema, separators=(",", ":"))
        return (
            f"<tool>\n"
            f"  <name>{self.name}</name>\n"
            f"  <description>{self.description}</description>\n"
            f"  <input_schema>{schema_str}</input_schema>\n"
            f"</tool>"
        )

    def to_json_schema(self) -> dict:
        """Return a dict representing this tool's JSON schema (Gap 9)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    A dict-like container of Tool instances.

    Usage
    -----
    registry = ToolRegistry()
    registry.register(ReadTool())
    tool = registry.get("Read")
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        log.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_xml(self) -> str:
        """Render all tools as a <tools>…</tools> XML block."""
        inner = "\n\n".join(t.to_xml() for t in self._tools.values())
        return f"<tools>\n{inner}\n</tools>"

    def to_json_schema(self) -> list[dict]:
        """Render all tools as a list of JSON schema objects (Gap 9)."""
        return [t.to_json_schema() for t in self._tools.values()]
