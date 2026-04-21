"""
Prompt Layer — System Prompt
=============================
Builds the system prompt string that is prepended to every conversation.

Kept modular so future additions (memory injection, project-specific
CLAUDE.md equivalents, etc.) can be slotted in without touching the
orchestrator.
"""

from __future__ import annotations

import datetime
import os
import platform
import shutil
import subprocess

# ── Core identity and rules ───────────────────────────────────────────────────

_CORE = """\
You are CyberPaw, a local AI coding assistant running entirely on this machine. You have access to the user's filesystem and shell. You help with programming
tasks: reading code, making edits, running tests, explaining concepts, and
refactoring.

Operating rules:
- Before every tool call, write a brief <thought> block explaining your reasoning:
  <thought>I need to read src/App.tsx to understand how the terminal is initialized.</thought>
  {"tool": "Read", "input": {...}}
- Use the Write tool to create new files that do not exist yet.
- Always read a file before editing an existing one.
- For existing files, prefer targeted edits (Edit tool) over full rewrites (Write tool).
- Do not run destructive shell commands unless the user explicitly asks.
- Keep responses concise. Show your work via tool calls, not lengthy prose.

Autonomy rules — follow these exactly:
- Work autonomously until the task is fully complete. Do NOT stop mid-task to ask "should I continue?" or "what would you like next?"
- Only stop and ask the user a question if you are genuinely blocked: a required file is missing, a decision has irreversible consequences (e.g. deleting data), or the task is fundamentally ambiguous and cannot be reasonably inferred.
- If you can make a reasonable assumption, make it and proceed. State the assumption in a brief note, then keep working.
- After all tool calls for a task are done and you have verified the result, write a short summary of what was completed. That is the only time you address the user.

You are fully offline. Do not reference external URLs or cloud services.
"""

# ── Tool calling instructions ─────────────────────────────────────────────────

_TOOL_INSTRUCTIONS = """\
## Tool Use

To call a tool, emit a JSON object on a single line starting with {"tool": ...}.

Example — reading a file:
<thought>I'll read the main entry point to see the application structure.</thought>
{"tool": "Read", "input": {"file_path": "src/main.py"}}

Example — writing a new file:
<thought>I'll create a basic README with project instructions.</thought>
{"tool": "Write", "input": {"file_path": "README.md", "content": "# My Project"}}

Rules:
- The JSON object must be on a SINGLE line.
- After emitting a tool call, stop generating — the system will run the tool and return its result. You will then continue working.
- Tool results arrive in the next message as <tool_result> blocks.
- Never fabricate tool results. Always wait for the actual result.
- Use the exact tool names and parameter names listed in the tool schema below.
- You may call multiple tools across multiple turns to complete a task. Keep going until the task is done.
"""


def _git_context(cwd: str) -> str:
    """Gather basic git status for project context (Gap 6 Phase 1)."""
    if not shutil.which("git"):
        return ""
    try:
        # Check if we are in a git repo
        subprocess.check_call(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1
        )
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, text=True, timeout=2
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=cwd, text=True, timeout=2
        ).strip()[:1000]
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            cwd=cwd, text=True, timeout=2
        ).strip()
        return (
            f"Git branch: {branch}\n"
            f"Recent commits:\n{log}\n"
            f"Working tree:\n{status}"
        )
    except Exception:
        return ""


def _find_project_instructions(cwd: str) -> str:
    """Find and read CLAUDE.md or AGENTS.md in cwd or parents (Gap 6 Phase 2)."""
    filenames = ["CLAUDE.md", "AGENTS.md"]
    curr = os.path.abspath(cwd)
    # Check up to 3 levels up
    for _ in range(4):
        for f in filenames:
            p = os.path.join(curr, f)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as fd:
                        content = fd.read(2000).strip()
                        return f"--- {f} ---\n{content}\n--- End of {f} ---"
                except Exception:
                    pass
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    return ""


def build_system_prompt(
    append: str = "",
) -> str:
    """
    Build the full system prompt string.
    This prompt is intended to be static to allow for KV caching.

    Parameters
    ----------
    append:
        Optional extra text appended at the end (from Settings).
    """
    core = _CORE.strip()
    parts = [core, _TOOL_INSTRUCTIONS.strip()]
    if append.strip():
        parts.append(append.strip())
    return "\n\n".join(parts)


def build_session_context(
    working_directory: str,
) -> str:
    """
    Build a string containing session-specific dynamic information.
    This should be injected into the first user message to keep the
    system prompt static (Gap 8).
    """
    parts = [
        f"Today's date is {datetime.date.today().isoformat()}. "
        f"I am running on {platform.system()}.",
        f"Working directory: {working_directory}"
    ]
    git = _git_context(working_directory)
    if git:
        parts.append(git)
    
    instructions = _find_project_instructions(working_directory)
    if instructions:
        parts.append(instructions)

    return "\n".join(parts)
