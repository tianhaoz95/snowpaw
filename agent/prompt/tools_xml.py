"""
Prompt Layer — Tools XML Renderer
===================================
Converts the ToolRegistry into a compact XML block that is injected
into the system prompt so the model knows what tools are available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.tool_registry import ToolRegistry


def render_tools_xml(registry: "ToolRegistry") -> str:
    """Return a <tools>…</tools> block listing all registered tools."""
    return registry.to_xml()


def render_tools_json(registry: "ToolRegistry") -> str:
    """Return a JSON string listing all registered tools (Gap 9)."""
    import json
    return json.dumps(registry.to_json_schema(), indent=2)
