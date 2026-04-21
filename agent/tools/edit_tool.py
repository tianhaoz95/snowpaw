"""Tool: Edit — exact string replacement in a file."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult
from harness.secret_scanner import scan
from .file_staleness import is_stale, clear_staleness
from .file_utils import suggest_paths, format_suggestions


_CURLY_QUOTE_MAP = str.maketrans({
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"'
})


def _normalise_quotes(s: str) -> str:
    """Map curly quotes to straight quotes."""
    return s.translate(_CURLY_QUOTE_MAP)


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

        # Secret scanning (Gap 10)
        warning = ""
        secrets = scan(new)
        if secrets:
            warning = "⚠ Possible credential in output: " + ", ".join(secrets) + "\n\n"

        if not os.path.isfile(path):
            suggestions = suggest_paths(input["file_path"], ctx.working_directory)
            return ToolResult.error(
                f"File not found: {path}. {format_suggestions(suggestions)}\n"
                "If you want to create a new file, use the Write tool instead."
            )

        if is_stale(ctx.session_id, path):
            return ToolResult.error(
                f"File {os.path.basename(path)} was modified since it was last read. "
                "Read the file again to get the latest content before editing."
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.error(str(e))

        # Try exact match first
        start_idx = content.find(old)
        match_len = len(old)

        if start_idx == -1:
            # Try normalising quotes (Gap 4)
            norm_content = _normalise_quotes(content)
            norm_old = _normalise_quotes(old)
            start_idx = norm_content.find(norm_old)
            match_len = len(norm_old)

        if start_idx == -1:
            return ToolResult.error(
                f"old_string not found in {os.path.basename(path)}. "
                "Make sure you copied the exact text including whitespace."
            )

        # Check for multiple matches
        if start_idx != -1:
            # Check if there's another match after the first one
            second_idx = content.find(old, start_idx + 1)
            if second_idx == -1:
                # Also check normalized content for multiple matches
                norm_content = _normalise_quotes(content)
                norm_old = _normalise_quotes(old)
                second_idx = norm_content.find(norm_old, start_idx + 1)

            if second_idx != -1:
                return ToolResult.error(
                    f"old_string appears multiple times in {os.path.basename(path)}. "
                    "Provide more surrounding context to make it unique."
                )

        # Apply normalization to new_string as well (Gap 4)
        new = _normalise_quotes(new)

        # Splice the replacement
        new_content = content[:start_idx] + new + content[start_idx + match_len:]

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult.error(str(e))

        clear_staleness(ctx.session_id, path)
        summary = f"Edited {os.path.basename(path)}"
        return ToolResult.ok(f"{warning}Successfully replaced text in {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
