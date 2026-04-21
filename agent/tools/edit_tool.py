# Tool: Edit -- exact string replacement in a file.

from __future__ import annotations

import difflib
import os

from harness.tool_registry import Tool, ToolContext, ToolResult
from harness.secret_scanner import scan
from .file_staleness import is_stale, clear_staleness, record_read
from .file_utils import suggest_paths, format_suggestions


# Map curly/smart quotes to straight ASCII equivalents
_CURLY_QUOTE_MAP = str.maketrans({
    "'": "'",  # left single quotation mark
    "'": "'",  # right single quotation mark
    "“": '"',  # left double quotation mark
    "”": '"',  # right double quotation mark
})

# Characters that constitute a "natural boundary" -- old_string must end
# at one of these (or at end-of-string) to be considered a valid match.
# This prevents partial/truncated old_strings from silently corrupting files.
_BOUNDARY_CHARS = set(';\n} \t"\'`')


def _normalise(s: str) -> str:
    """Normalise curly quotes and line endings to straight/LF."""
    return s.translate(_CURLY_QUOTE_MAP).replace("\r\n", "\n").replace("\r", "\n")


def _ends_at_boundary(content: str, start: int, length: int, old: str = "") -> bool:
    """
    Return True if the match ends at a natural token boundary.

    A match is valid when BOTH of the following hold:
    1. The last character of old_string itself is a boundary char (semicolon,
       newline, bracket, quote, whitespace, etc.). This catches truncated
       old_strings that end mid-word (e.g. "insert('transactions', row").
    2. The character immediately after the match in content is a boundary char,
       OR the match extends to EOF.

    Note: EOF does NOT relax condition 1 -- a truncated old_string that happens
    to be at the end of the file is still a truncated old_string.
    """
    end = start + length

    # Condition 1: old_string ends at a boundary char
    last_old_char = old[-1] if old else (content[end - 1] if length > 0 else "")
    if last_old_char not in _BOUNDARY_CHARS:
        return False

    # Condition 2: next char in file is a boundary (or EOF)
    return end >= len(content) or content[end] in _BOUNDARY_CHARS


def _strip_indent(s: str) -> str:
    """Strip leading whitespace from every line."""
    return "\n".join(line.lstrip() for line in s.splitlines())


def _find_match(content: str, old: str) -> "tuple[int, int] | None":
    """
    Try progressively looser matching strategies.
    Returns (start_idx, match_len) in the ORIGINAL content, or None.

    All returned indices/lengths are valid against the original content string.

    Pass 1 - exact match
    Pass 2 - normalised quotes + line endings (indices mapped back to original)
    Pass 3 - indent-stripped match (handles wrong indentation)

    Every candidate match is validated against _ends_at_boundary to reject
    truncated old_strings that only partially match a line.
    """
    # Pass 1: exact
    idx = content.find(old)
    if idx != -1 and _ends_at_boundary(content, idx, len(old), old):
        return idx, len(old)

    # Pass 2: normalise quotes and line endings, but map index back to original.
    # We cannot use the normalised index/length directly against the original
    # content because normalisation may change string length (e.g. \r\n -> \n).
    # Instead, find the match in normalised space, count newlines to get the
    # line number, then locate that line in the original content.
    nc = _normalise(content)
    no = _normalise(old)
    nc_idx = nc.find(no)
    if nc_idx != -1:
        # Map nc_idx back to original content via line number
        line_no = nc[:nc_idx].count("\n")
        char_in_line = nc_idx - nc[:nc_idx].rfind("\n") - 1
        orig_lines = content.splitlines(keepends=True)
        if line_no < len(orig_lines):
            orig_line_start = sum(len(l) for l in orig_lines[:line_no])
            orig_start = orig_line_start + char_in_line
            # Determine match length by counting lines in no
            no_line_count = no.count("\n")
            if no_line_count == 0:
                # Single-line: match_len is length of no (same chars, no \r\n diff)
                orig_end_line = line_no
                orig_end = orig_line_start + char_in_line + len(no)
                # Adjust for any \r that was stripped
                orig_end = min(orig_end, sum(len(l) for l in orig_lines[:line_no + 1]))
            else:
                end_line_no = line_no + no_line_count
                if end_line_no < len(orig_lines):
                    no_last_line = no.split("\n")[-1]
                    orig_end = sum(len(l) for l in orig_lines[:end_line_no]) + len(no_last_line)
                else:
                    orig_end = len(content)
            match_len = orig_end - orig_start
            if match_len > 0 and _ends_at_boundary(content, orig_start, match_len, no):
                return orig_start, match_len

    # Pass 3: strip indentation, find match, re-anchor to original.
    # Only use this pass for multi-line old_strings or when old_string
    # ends at a natural boundary -- single-line partial matches are too
    # likely to be truncation artifacts.
    stripped_old = _strip_indent(no)
    stripped_content = _strip_indent(nc)
    # Require the stripped old to end at a boundary in the stripped content
    s_idx = stripped_content.find(stripped_old)
    if s_idx != -1:
        s_end = s_idx + len(stripped_old)
        s_end_ok = (
            s_end >= len(stripped_content)
            or stripped_content[s_end] in _BOUNDARY_CHARS
            or (len(stripped_old) > 0 and stripped_old[-1] in _BOUNDARY_CHARS)
        )
        if s_end_ok:
            line_no = stripped_content[:s_idx].count("\n")
            orig_lines = nc.splitlines()
            if line_no < len(orig_lines):
                first_old_line = _strip_indent(no.splitlines()[0]) if no.splitlines() else ""
                for li in range(line_no, min(line_no + 3, len(orig_lines))):
                    if _strip_indent(orig_lines[li]).startswith(first_old_line[:20]):
                        orig_start = sum(len(l) + 1 for l in orig_lines[:li])
                        old_line_count = no.count("\n") + 1
                        orig_end = sum(len(l) + 1 for l in orig_lines[:li + old_line_count])
                        match_len = orig_end - orig_start
                        if _ends_at_boundary(content, orig_start, match_len, no):
                            return orig_start, match_len

    return None


def _closest_lines(content: str, old: str, context: int = 3) -> str:
    """
    Return a snippet of the file near the closest matching line to old_string,
    to help the model self-correct on the next attempt.
    """
    old_first_line = old.strip().splitlines()[0].strip() if old.strip() else ""
    if not old_first_line:
        return ""

    content_lines = content.splitlines()
    best_ratio = 0.0
    best_lineno = 0
    for i, line in enumerate(content_lines):
        r = difflib.SequenceMatcher(None, old_first_line, line.strip()).ratio()
        if r > best_ratio:
            best_ratio = r
            best_lineno = i

    if best_ratio < 0.3:
        return ""

    lo = max(0, best_lineno - context)
    hi = min(len(content_lines), best_lineno + context + 1)
    lines = []
    for i in range(lo, hi):
        prefix = "-> " if i == best_lineno else "   "
        lines.append(f"{prefix}{i+1:4d} | {content_lines[i]}")
    return "\n".join(lines)


class EditTool(Tool):
    name = "Edit"
    description = (
        "Replace an exact string in a file with new text. "
        "old_string must appear exactly once in the file. "
        "Always Read the file immediately before calling Edit "
        "to get the current exact content -- never rely on what you wrote earlier."
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

        warning = ""
        secrets = scan(new)
        if secrets:
            warning = "Possible credential in output: " + ", ".join(secrets) + "\n\n"

        if not os.path.isfile(path):
            suggestions = suggest_paths(input["file_path"], ctx.working_directory)
            return ToolResult.error(
                f"File not found: {path}. {format_suggestions(suggestions)}\n"
                "Use the Write tool to create a new file."
            )

        if is_stale(ctx.session_id, path):
            return ToolResult.error(
                f"{os.path.basename(path)} was modified since last read. "
                "Read it again before editing."
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.error(str(e))

        match = _find_match(content, old)

        if match is None:
            snippet = _closest_lines(content, old)
            # Always show the file content so the model can fix old_string
            # without a separate Read round-trip.
            # Cap at 120 lines to avoid flooding the context.
            file_lines = content.splitlines()
            MAX_INLINE = 120
            if len(file_lines) <= MAX_INLINE:
                file_preview = "\n".join(
                    f"{i+1:4d} | {l}" for i, l in enumerate(file_lines)
                )
                file_hint = f"\n\nCurrent file content:\n{file_preview}"
            else:
                # File is large — show closest region + a note
                if snippet:
                    file_hint = f"\n\nClosest lines in the file:\n{snippet}"
                else:
                    # No similar lines found — show the first 40 lines
                    preview = "\n".join(
                        f"{i+1:4d} | {l}" for i, l in enumerate(file_lines[:40])
                    )
                    file_hint = (
                        f"\n\nFile is large ({len(file_lines)} lines). "
                        f"First 40 lines:\n{preview}\n"
                        "Use the Read tool with offset/limit to see specific sections."
                    )
            return ToolResult.error(
                f"old_string not found in {os.path.basename(path)}. "
                f"Use the exact text shown below as old_string.{file_hint}"
            )

        start_idx, match_len = match

        # Check for multiple matches using the normalised content
        nc = _normalise(content)
        no = _normalise(old)
        first = nc.find(no)
        if first != -1 and nc.find(no, first + 1) != -1:
            return ToolResult.error(
                f"old_string appears multiple times in {os.path.basename(path)}. "
                "Include more surrounding context to make it unique."
            )

        new_content = content[:start_idx] + _normalise(new) + content[start_idx + match_len:]

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult.error(str(e))

        # Record mtime so the next Edit has a valid staleness baseline
        record_read(ctx.session_id, path)
        summary = f"Edited {os.path.basename(path)}"
        return ToolResult.ok(f"{warning}Successfully edited {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
