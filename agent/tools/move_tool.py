"""Tool: Move — move or rename a file or directory."""

from __future__ import annotations

import os
import shutil

from harness.tool_registry import Tool, ToolContext, ToolResult


class MoveTool(Tool):
    name = "Move"
    description = (
        "Move or rename a file or directory. "
        "The destination parent directory must already exist. "
        "Will overwrite an existing file at the destination."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Path to the file or directory to move.",
            },
            "destination": {
                "type": "string",
                "description": "Target path (new name or location).",
            },
        },
        "required": ["source", "destination"],
    }

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        src = _resolve(input["source"], ctx.working_directory)
        dst = _resolve(input["destination"], ctx.working_directory)

        if not os.path.exists(src):
            return ToolResult.error(f"Source not found: {src}")

        dst_parent = os.path.dirname(dst)
        if dst_parent and not os.path.isdir(dst_parent):
            return ToolResult.error(
                f"Destination directory does not exist: {dst_parent}"
            )

        try:
            shutil.move(src, dst)
        except OSError as e:
            return ToolResult.error(str(e))

        src_name = os.path.basename(src)
        dst_name = os.path.basename(dst)
        summary = (
            f"Renamed {src_name} → {dst_name}"
            if os.path.dirname(src) == os.path.dirname(dst)
            else f"Moved {src_name} → {dst}"
        )
        return ToolResult.ok(f"Moved {src} → {dst}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
