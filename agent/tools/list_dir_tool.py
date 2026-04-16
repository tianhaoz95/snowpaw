"""Tool: ListDir — list directory contents."""

from __future__ import annotations

import os
import stat

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_ENTRIES = 300


class ListDirTool(Tool):
    name = "ListDir"
    description = (
        "List the contents of a directory. "
        "Shows file names, sizes, and types. "
        "Defaults to the current working directory."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to list. Defaults to working directory.",
            },
        },
        "required": [],
    }

    def is_read_only(self, input: dict) -> bool:
        return True

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        raw = input.get("path") or ctx.working_directory
        path = _resolve(raw, ctx.working_directory)

        if not os.path.isdir(path):
            return ToolResult.error(f"Not a directory: {path}")

        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError as e:
            return ToolResult.error(str(e))

        lines: list[str] = []
        for entry in entries[:MAX_ENTRIES]:
            try:
                s = entry.stat(follow_symlinks=False)
            except OSError:
                lines.append(f"  {'d' if entry.is_dir() else '-'}  {entry.name}")
                continue

            kind = "d" if stat.S_ISDIR(s.st_mode) else ("l" if stat.S_ISLNK(s.st_mode) else "-")
            size = _fmt_size(s.st_size) if kind == "-" else ""
            lines.append(f"  {kind}  {size:>8}  {entry.name}")

        if len(entries) > MAX_ENTRIES:
            lines.append(f"  … ({len(entries) - MAX_ENTRIES} more entries)")

        output = f"{path}/\n" + "\n".join(lines)
        summary = f"Listed {min(len(entries), MAX_ENTRIES)} entries in {os.path.basename(path)}"
        return ToolResult.ok(output, summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))


def _fmt_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}T"
