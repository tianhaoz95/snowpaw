"""Tool: Write — write or overwrite a file."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult
from harness.secret_scanner import scan
from .file_staleness import clear_staleness, record_read
from .file_utils import suggest_paths, format_suggestions


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

        # Secret scanning (Gap 10)
        warning = ""
        secrets = scan(content)
        if secrets:
            warning = "⚠ Possible credential in output: " + ", ".join(secrets) + "\n\n"

        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            parent_rel = os.path.dirname(input["file_path"])
            suggestions = suggest_paths(parent_rel, ctx.working_directory, folders_only=True)
            if suggestions:
                return ToolResult.error(
                    f"Directory not found: {parent}. {format_suggestions(suggestions)}\n"
                    "Create the directory first or use the correct path."
                )

        os.makedirs(parent or ".", exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(str(e))

        # Record mtime so subsequent Edit calls have a valid staleness baseline
        clear_staleness(ctx.session_id, path)
        record_read(ctx.session_id, path)
        lines = content.count("\n") + 1
        summary = f"Wrote {lines} lines to {os.path.basename(path)}"
        return ToolResult.ok(f"{warning}Successfully wrote {len(content)} bytes to {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
