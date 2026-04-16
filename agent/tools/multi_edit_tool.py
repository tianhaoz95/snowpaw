"""Tool: MultiEdit — apply multiple exact-string replacements to a single file atomically."""

from __future__ import annotations

import os

from harness.tool_registry import Tool, ToolContext, ToolResult


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

        if not os.path.isfile(path):
            return ToolResult.error(f"File not found: {path}")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.error(str(e))

        for i, edit in enumerate(edits):
            old: str = edit["old_string"]
            new: str = edit["new_string"]
            count = content.count(old)
            if count == 0:
                return ToolResult.error(
                    f"Edit #{i + 1}: old_string not found in {os.path.basename(path)}. "
                    "Make sure you copied the exact text including whitespace."
                )
            if count > 1:
                return ToolResult.error(
                    f"Edit #{i + 1}: old_string appears {count} times in "
                    f"{os.path.basename(path)}. Provide more surrounding context."
                )
            content = content.replace(old, new, 1)

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolResult.error(str(e))

        summary = f"Applied {len(edits)} edit(s) to {os.path.basename(path)}"
        return ToolResult.ok(f"Successfully applied {len(edits)} edit(s) to {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
