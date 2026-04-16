"""Tool: Read — read file contents with line numbers."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult


class ReadTool(Tool):
    name = "Read"
    description = (
        "Read the contents of a file. Returns the file content with line numbers. "
        "Use offset and limit to read a specific range of lines."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or working-directory-relative path to the file.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Default: 1.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Default: 200.",
            },
        },
        "required": ["file_path"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        raw_path: str = input["file_path"]
        offset: int = max(1, int(input.get("offset", 1)))
        limit: int = int(input.get("limit", 200))

        path = _resolve(raw_path, ctx.working_directory)

        if not os.path.isfile(path):
            return ToolResult.error(f"File not found: {path}")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return ToolResult.error(str(e))

        total = len(lines)
        start = offset - 1  # convert to 0-indexed
        end = min(start + limit, total)
        selected = lines[start:end]

        numbered = "".join(
            f"{start + i + 1}\t{line}" for i, line in enumerate(selected)
        )
        summary = f"Read {end - start} lines from {os.path.basename(path)}"
        return ToolResult.ok(numbered, summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
