"""Tool: Glob — find files matching a glob pattern."""

from __future__ import annotations

import fnmatch
import os

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_RESULTS = 500


class GlobTool(Tool):
    name = "Glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
        "Returns matching paths sorted by modification time, newest first. "
        "Results are capped at 500 entries."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match against file paths.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to working directory.",
            },
        },
        "required": ["pattern"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        import glob as glob_module

        pattern: str = input["pattern"]
        base: str = input.get("path") or ctx.working_directory
        base = _resolve(base, ctx.working_directory)

        if not os.path.isdir(base):
            return ToolResult.error(f"Directory not found: {base}")

        search = os.path.join(base, pattern)
        try:
            matches = glob_module.glob(search, recursive=True)
        except Exception as e:
            return ToolResult.error(str(e))

        # Sort by mtime descending, cap results
        matches.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        matches = matches[:MAX_RESULTS]

        if not matches:
            return ToolResult.ok("No files matched.", "No matches")

        # Show relative paths when possible
        rel = [os.path.relpath(m, base) for m in matches]
        output = "\n".join(rel)
        summary = f"{len(matches)} file(s) matched '{pattern}'"
        return ToolResult.ok(output, summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
