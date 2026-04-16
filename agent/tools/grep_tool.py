"""Tool: Grep — search file contents with a regex."""

from __future__ import annotations

import os
import re

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_MATCHES = 200


class GrepTool(Tool):
    name = "Grep"
    description = (
        "Search file contents using a regular expression. "
        "Returns matching lines with file path and line number. "
        "Use the 'glob' parameter to restrict which files are searched."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to working directory.",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py').",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search. Default: false.",
            },
        },
        "required": ["pattern"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        import glob as glob_module

        pattern_str: str = input["pattern"]
        base: str = input.get("path") or ctx.working_directory
        base = _resolve(base, ctx.working_directory)
        file_glob: str = input.get("glob", "**/*")
        flags = re.IGNORECASE if input.get("case_insensitive") else 0

        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return ToolResult.error(f"Invalid regex: {e}")

        # Collect candidate files
        if os.path.isfile(base):
            files = [base]
        else:
            search = os.path.join(base, file_glob)
            files = [f for f in glob_module.glob(search, recursive=True) if os.path.isfile(f)]

        results: list[str] = []
        for filepath in sorted(files):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = os.path.relpath(filepath, base)
                            results.append(f"{rel}:{lineno}:{line.rstrip()}")
                            if len(results) >= MAX_MATCHES:
                                break
            except OSError:
                continue
            if len(results) >= MAX_MATCHES:
                break

        if not results:
            return ToolResult.ok("No matches found.", "No matches")

        output = "\n".join(results)
        if len(results) >= MAX_MATCHES:
            output += f"\n… (truncated at {MAX_MATCHES} matches)"
        summary = f"{len(results)} match(es) for '{pattern_str}'"
        return ToolResult.ok(output, summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
