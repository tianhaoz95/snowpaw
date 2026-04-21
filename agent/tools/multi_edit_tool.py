"""Tool: MultiEdit — apply multiple exact-string replacements to a single file atomically."""

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


class MultiEditTool(Tool):
    name = "MultiEdit"
    description = (
        "Apply multiple find-and-replace edits to a single file in one atomic operation. "
        "Each edit must have a unique old_string. Edits are applied in order; later edits "
        "see the result of earlier ones. Always read the file first to confirm exact strings."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "edits": {
                "type": "array",
                "description": "Ordered list of replacements to apply.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {
                            "type": "string",
                            "description": "Exact string to find. Must appear exactly once at the time this edit runs.",
                        },
                        "new_string": {
                            "type": "string",
                            "description": "Replacement string.",
                        },
                    },
                    "required": ["old_string", "new_string"],
                },
                "minItems": 1,
            },
        },
        "required": ["file_path", "edits"],
    }

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(input["file_path"], ctx.working_directory)
        edits: list[dict] = input["edits"]

        # Secret scanning (Gap 10)
        all_secrets = []
        for edit in edits:
            all_secrets.extend(scan(edit["new_string"]))
        
        warning = ""
        if all_secrets:
            # unique secrets
            unique_secrets = sorted(list(set(all_secrets)))
            warning = "⚠ Possible credential in output: " + ", ".join(unique_secrets) + "\n\n"

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

        for i, edit in enumerate(edits):
            old: str = edit["old_string"]
            new: str = _normalise_quotes(edit["new_string"])
            
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
                    f"Edit #{i + 1}: old_string not found in {os.path.basename(path)}. "
                    "Make sure you copied the exact text including whitespace."
                )
            
            # Check for multiple matches
            second_idx = content.find(old, start_idx + 1)
            if second_idx == -1:
                norm_content = _normalise_quotes(content)
                norm_old = _normalise_quotes(old)
                second_idx = norm_content.find(norm_old, start_idx + 1)
                
            if second_idx != -1:
                return ToolResult.error(
                    f"Edit #{i + 1}: old_string appears multiple times in "
                    f"{os.path.basename(path)}. Provide more surrounding context."
                )

            # Apply replacement
            content = content[:start_idx] + new + content[start_idx + match_len:]

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(str(e))

        clear_staleness(ctx.session_id, path)
        summary = f"Applied {len(edits)} edit(s) to {os.path.basename(path)}"
        return ToolResult.ok(f"{warning}Successfully applied {len(edits)} edit(s) to {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
