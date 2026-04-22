# Tool: Edit -- exact string replacement in a file.
#
# Matching pipeline adapted from aider's search_replace.py
# (https://github.com/Aider-AI/aider), MIT licence.
# Strategies used (in order):
#   1. Exact str.replace  (with 4 preprocessing combos)
#   2. dmp_lines_apply    (diff-match-patch at line granularity, same combos)
# Preprocessing combos: raw | strip-blank-lines | relative-indent | both
# RelativeIndenter and dmp_lines_apply are direct ports from aider.

from __future__ import annotations

import difflib
import os

from harness.tool_registry import Tool, ToolContext, ToolResult
from harness.secret_scanner import scan
from .file_staleness import is_stale, is_written_unread, record_read
from .file_utils import suggest_paths, format_suggestions


# ---------------------------------------------------------------------------
# RelativeIndenter  (ported from aider)
# ---------------------------------------------------------------------------

class RelativeIndenter:
    """
    Rewrites text so each line's leading whitespace is expressed as a *delta*
    from the previous line rather than an absolute indent level.  This makes
    search_and_replace succeed even when old_string uses a different base
    indentation than the file.

    Outdents are marked with a unicode arrow character that is guaranteed not
    to appear in either text.
    """

    def __init__(self, texts: list[str]) -> None:
        chars: set[str] = set()
        for t in texts:
            chars.update(t)
        marker = "←"  # left arrow
        if marker in chars:
            for cp in range(0x10FFFF, 0x10000, -1):
                candidate = chr(cp)
                if candidate not in chars:
                    marker = candidate
                    break
        self.marker = marker

    def make_relative(self, text: str) -> str:
        lines = text.splitlines(keepends=True)
        output: list[str] = []
        prev_indent = ""
        for line in lines:
            stripped = line.rstrip("\n\r")
            indent_len = len(stripped) - len(stripped.lstrip())
            indent = line[:indent_len]
            change = indent_len - len(prev_indent)
            if change > 0:
                cur_indent = indent[-change:]
            elif change < 0:
                cur_indent = self.marker * -change
            else:
                cur_indent = ""
            output.append(cur_indent + "\n" + line[indent_len:])
            prev_indent = indent
        return "".join(output)

    def make_absolute(self, text: str) -> str:
        lines = text.splitlines(keepends=True)
        output: list[str] = []
        prev_indent = ""
        for i in range(0, len(lines), 2):
            dent = lines[i].rstrip("\r\n")
            non_indent = lines[i + 1]
            if dent.startswith(self.marker):
                cur_indent = prev_indent[: -len(dent)]
            else:
                cur_indent = prev_indent + dent
            if not non_indent.rstrip("\r\n"):
                output.append(non_indent)
            else:
                output.append(cur_indent + non_indent)
            prev_indent = cur_indent
        result = "".join(output)
        if self.marker in result:
            raise ValueError("RelativeIndenter: failed to restore absolute indents")
        return result


# ---------------------------------------------------------------------------
# Preprocessing helpers
# ---------------------------------------------------------------------------

def _strip_blank_lines(texts: list[str]) -> list[str]:
    return [t.strip("\n") + "\n" for t in texts]


def _apply_relative_indent(texts: list[str]) -> "tuple[RelativeIndenter, list[str]]":
    ri = RelativeIndenter(texts)
    return ri, [ri.make_relative(t) for t in texts]


_CURLY_QUOTE_MAP = str.maketrans({
    "‘": "'",  # left single quotation mark
    "’": "'",  # right single quotation mark
    "“": '"',  # left double quotation mark
    "”": '"',  # right double quotation mark
})


def _normalise_endings(text: str) -> str:
    return text.translate(_CURLY_QUOTE_MAP).replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------
# Strategy 1: exact str.replace  (with boundary validation)
# ---------------------------------------------------------------------------

# Characters that a valid old_string must end with.
# Excludes ) and ] because "foo(bar)" is a common truncation point.
_BOUNDARY_CHARS = frozenset(';\n} \t"\'`')


def _ends_at_boundary(search: str, original: str) -> bool:
    """
    Return True if the match is at a natural token boundary.
    Requires:
      1. search itself ends with a boundary char (rejects mid-word truncations)
      2. the character after the match in original is a boundary char or EOF
    """
    if not search:
        return False
    if search[-1] not in _BOUNDARY_CHARS:
        return False
    idx = original.find(search)
    if idx == -1:
        return False
    end = idx + len(search)
    return end >= len(original) or original[end] in _BOUNDARY_CHARS


def _search_and_replace(search: str, replace: str, original: str) -> "str | None":
    if search not in original:
        return None
    if original.count(search) > 1:
        return None  # ambiguous
    if not _ends_at_boundary(search, original):
        return None  # likely a truncated old_string
    return original.replace(search, replace, 1)


# ---------------------------------------------------------------------------
# Strategy 2: dmp_lines_apply  (ported from aider)
# ---------------------------------------------------------------------------

_LINE_PADDING = 100


def _dmp_lines_apply(search: str, replace: str, original: str) -> "str | None":
    # All three texts must end with a newline for line-based dmp to work
    for t in (search, replace, original):
        if not t.endswith("\n"):
            return None

    try:
        from diff_match_patch import diff_match_patch  # type: ignore[import]
    except ImportError:
        return None

    dmp = diff_match_patch()
    dmp.Diff_Timeout = 5
    dmp.Match_Threshold = 0.1
    dmp.Match_Distance = 100_000
    dmp.Match_MaxBits = 32
    dmp.Patch_Margin = 1

    all_text = search + replace + original
    all_lines, _, mapping = dmp.diff_linesToChars(all_text, "")

    s_n = len(search.splitlines())
    r_n = len(replace.splitlines())

    search_lines  = all_lines[:s_n]
    replace_lines = all_lines[s_n: s_n + r_n]
    original_lines = all_lines[s_n + r_n:]

    diff = dmp.diff_main(search_lines, replace_lines, None)
    dmp.diff_cleanupSemantic(diff)
    dmp.diff_cleanupEfficiency(diff)

    patches = dmp.patch_make(search_lines, diff)
    new_lines, success = dmp.patch_apply(patches, original_lines)

    if False in success:
        return None

    new_text = "".join(mapping[ord(c)] for c in new_lines)
    return new_text


# ---------------------------------------------------------------------------
# Indent rewriting: detect and correct wrong base indentation in old_string
# ---------------------------------------------------------------------------

def _get_leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _reindent(search: str, replace: str, original: str) -> "tuple[str, str] | None":
    """
    If search uses a different indentation unit than original, rescale all
    indentation in search and replace to match original's unit.

    Approach: find the first non-blank line of search in original (by stripped
    content), measure the indent ratio between the two, then rescale every
    indented line in search and replace by that ratio.
    """
    search_lines = search.splitlines()
    orig_lines = original.splitlines()

    # Find first non-blank line of search and its indent
    s_first = next((l for l in search_lines if l.strip()), None)
    if s_first is None:
        return None
    s_indent = _get_leading_spaces(s_first)
    s_first_stripped = s_first.strip()

    # Find the matching line in original
    o_indent = None
    for orig_line in orig_lines:
        if orig_line.strip() == s_first_stripped:
            o_indent = _get_leading_spaces(orig_line)
            break
    if o_indent is None:
        return None
    if o_indent == s_indent:
        return None  # already aligned

    def rescale(text: str) -> str:
        result = []
        for line in text.splitlines(keepends=True):
            if not line.strip():
                result.append(line)
                continue
            cur = _get_leading_spaces(line)
            if s_indent > 0:
                # Scale proportionally: new = o_indent + (cur - s_indent) * (o_indent / s_indent)
                # Use integer arithmetic to avoid float rounding
                new_indent = o_indent + (cur - s_indent) * o_indent // s_indent
            else:
                new_indent = o_indent + cur
            result.append(" " * max(0, new_indent) + line.lstrip(" \t"))
        return "".join(result)

    return rescale(search), rescale(replace)


# ---------------------------------------------------------------------------
# Flexible pipeline (mirrors aider's flexible_search_and_replace)
# ---------------------------------------------------------------------------

def _try_strategy(strategy, search: str, replace: str, original: str,
                  strip_blank: bool, rel_indent: bool) -> "str | None":
    texts = [search, replace, original]

    if strip_blank:
        texts = _strip_blank_lines(texts)
    ri = None
    if rel_indent:
        ri, texts = _apply_relative_indent(texts)

    result = strategy(*texts)

    if result and ri:
        try:
            result = ri.make_absolute(result)
        except ValueError:
            return None

    return result


_PREPROCS = [
    (False, False),
    (True,  False),
    (False, True),
    (True,  True),
]


def apply_edit(search: str, replace: str, original: str) -> "str | None":
    """
    Try to apply search->replace against original using aider's strategy
    pipeline.  Returns the new file content, or None if no strategy succeeded.
    """
    # Normalise line endings first
    search   = _normalise_endings(search)
    replace  = _normalise_endings(replace)
    original = _normalise_endings(original)

    # Strategy pipeline: exact str.replace then dmp, each with 4 preprocessing combos
    for strategy in (_search_and_replace, _dmp_lines_apply):
        for strip_blank, rel_indent in _PREPROCS:
            result = _try_strategy(strategy, search, replace, original,
                                   strip_blank, rel_indent)
            if result is not None:
                return result

    # Indent-correction pass: detect wrong base indentation and retry
    reindented = _reindent(search, replace, original)
    if reindented is not None:
        s2, r2 = reindented
        for strategy in (_search_and_replace, _dmp_lines_apply):
            for strip_blank, rel_indent in _PREPROCS:
                result = _try_strategy(strategy, s2, r2, original,
                                       strip_blank, rel_indent)
                if result is not None:
                    return result

    return None


# ---------------------------------------------------------------------------
# Error hint: show file content so model can self-correct
# ---------------------------------------------------------------------------

def _file_hint(content: str, old: str) -> str:
    lines = content.splitlines()
    MAX_INLINE = 120
    if len(lines) <= MAX_INLINE:
        numbered = "\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines))
        return f"\n\nCurrent file content:\n{numbered}"

    # Large file: find closest region
    old_first = old.strip().splitlines()[0].strip() if old.strip() else ""
    best_ratio, best_lineno = 0.0, 0
    for i, line in enumerate(lines):
        r = difflib.SequenceMatcher(None, old_first, line.strip()).ratio()
        if r > best_ratio:
            best_ratio, best_lineno = r, i

    if best_ratio >= 0.3:
        lo = max(0, best_lineno - 3)
        hi = min(len(lines), best_lineno + 4)
        snippet = "\n".join(
            f"{'-> ' if i == best_lineno else '   '}{i+1:4d} | {lines[i]}"
            for i in range(lo, hi)
        )
        return f"\n\nClosest lines in the file:\n{snippet}"

    preview = "\n".join(f"{i+1:4d} | {lines[i]}" for i in range(min(40, len(lines))))
    return (
        f"\n\nFile is large ({len(lines)} lines). First 40 lines:\n{preview}\n"
        "Use the Read tool with offset/limit to see other sections."
    )


# ---------------------------------------------------------------------------
# EditTool
# ---------------------------------------------------------------------------

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

        if is_written_unread(ctx.session_id, path):
            return ToolResult.error(
                f"{os.path.basename(path)} was just written but not yet read back. "
                "Read the file first to confirm its exact content, then call Edit "
                "with the correct old_string from that Read result."
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            return ToolResult.error(str(e))

        new_content = apply_edit(old, new, content)

        if new_content is None:
            return ToolResult.error(
                f"old_string not found in {os.path.basename(path)}. "
                f"Use the exact text shown below as old_string."
                + _file_hint(content, old)
            )

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult.error(str(e))

        record_read(ctx.session_id, path)
        summary = f"Edited {os.path.basename(path)}"
        return ToolResult.ok(f"{warning}Successfully edited {path}", summary)


def _resolve(path: str, cwd: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd, path))
