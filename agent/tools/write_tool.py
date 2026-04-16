"""Tool: Write — write or overwrite a file."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult


class WriteTool(Tool):
    name = "Write"
    description = (
        "Write content to a file, creating it if it does not exist or "
        "overwriting it if it does. Always read the file first if it exists "
        "to avoid unintentional data loss."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(input["file_path"], ctx.working_directory)
        content: str = input["content"]

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(str(e))

        lines = content.count("\n") + 1
        summary = f"Wrote {lines} lines to {os.path.basename(path)}"
        return ToolResult.ok(f"Successfully wrote {len(content)} bytes to {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
