"""Tool: DeleteFile — delete a file or an empty directory."""

from __future__ import annotations

import os
import shutil

from harness.tool_registry import Tool, ToolContext, ToolResult


class DeleteFileTool(Tool):
    name = "DeleteFile"
    description = (
        "Delete a file or directory. "
        "Directories are deleted recursively only when recursive=true is explicitly set. "
        "Use with caution — this operation cannot be undone."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file or directory to delete.",
            },
            "recursive": {
                "type": "boolean",
                "description": (
                    "If true, delete a directory and all its contents. "
                    "Default: false (only empty directories or files are deleted)."
                ),
            },
        },
        "required": ["path"],
    }

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        raw = input["path"]
        recursive: bool = bool(input.get("recursive", False))
        path = _resolve(raw, ctx.working_directory)

        if not os.path.exists(path):
            return ToolResult.error(f"Path not found: {path}")

        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
                summary = f"Deleted file {os.path.basename(path)}"
                return ToolResult.ok(f"Deleted {path}", summary)

            if os.path.isdir(path):
                if recursive:
                    shutil.rmtree(path)
                    summary = f"Deleted directory {os.path.basename(path)} (recursive)"
                    return ToolResult.ok(f"Deleted directory {path} recursively", summary)
                else:
                    os.rmdir(path)  # raises OSError if not empty
                    summary = f"Deleted directory {os.path.basename(path)}"
                    return ToolResult.ok(f"Deleted directory {path}", summary)

        except OSError as e:
            hint = " (use recursive=true to delete non-empty directories)" if os.path.isdir(path) else ""
            return ToolResult.error(f"{e}{hint}")

        return ToolResult.error(f"Unknown path type: {path}")


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
