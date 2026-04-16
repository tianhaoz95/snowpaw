"""Tool: Edit — exact string replacement in a file."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult


class EditTool(Tool):
    name = "Edit"
    description = (
        "Replace an exact string in a file with new text. "
        "The old_string must appear exactly once in the file. "
        "Always read the file first to confirm the exact string to replace."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace. Must be unique in the file.",
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(input["file_path"], ctx.working_directory)
        old: str = input["old_string"]
        new: str = input["new_string"]

        if not os.path.isfile(path):
            return ToolResult.error(
                f"File not found: {path}. "
                "If you want to create a new file, use the Write tool instead."
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.error(str(e))

        count = content.count(old)
        if count == 0:
            return ToolResult.error(
                f"old_string not found in {os.path.basename(path)}. "
                "Make sure you copied the exact text including whitespace."
            )
        if count > 1:
            return ToolResult.error(
                f"old_string appears {count} times in {os.path.basename(path)}. "
                "Provide more surrounding context to make it unique."
            )

        new_content = content.replace(old, new, 1)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult.error(str(e))

        summary = f"Edited {os.path.basename(path)}"
        return ToolResult.ok(f"Successfully replaced text in {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
