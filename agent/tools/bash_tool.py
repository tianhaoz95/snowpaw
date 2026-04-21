"""Tool: Bash — run a shell command in the working directory."""

from __future__ import annotations

import asyncio
import os

from harness.background_tasks import REGISTRY, BackgroundTask
from harness.tool_registry import Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120       # seconds — hard kill deadline
AUTO_BG_THRESHOLD = 15      # seconds — promote to background if still running
MAX_OUTPUT_CHARS = 50_000

# Commands that are always blocked regardless of permission mode
BLOCKED_COMMANDS = frozenset([
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
    ":(){:|:&};:", "fork bomb",
])

# Commands that must never be auto-backgrounded (they're expected to be short)
_NO_AUTO_BG = frozenset(["sleep"])


def _should_auto_bg(command: str) -> bool:
    cmd = command.strip().split()[0] if command.strip() else ""
    return cmd not in _NO_AUTO_BG


def _truncate(output: str) -> str:
    if len(output) > MAX_OUTPUT_CHARS:
        half = MAX_OUTPUT_CHARS // 2
        return (
            output[:half]
            + f"\n\n… [{len(output) - MAX_OUTPUT_CHARS} chars truncated] …\n\n"
            + output[-half:]
        )
    return output


class BashTool(Tool):
    name = "Bash"
    description = (
        "Execute a shell command in the working directory. "
        "Output (stdout + stderr) is returned. "
        "For long-running commands set run_in_background=true to get a task ID "
        "immediately and check results later with TaskOutput. "
        "Commands that take longer than 15 seconds are automatically backgrounded."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default {DEFAULT_TIMEOUT}). "
                               "Only applies to foreground execution.",
            },
            "description": {
                "type": "string",
                "description": "Short human-readable description of what this command does.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "If true, launch the command immediately in the background and "
                    "return a task_id without waiting for it to finish. "
                    "Use TaskOutput to retrieve the result later."
                ),
            },
        },
        "required": ["command"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        command: str = input["command"]
        timeout: int = int(input.get("timeout", DEFAULT_TIMEOUT))
        run_in_background: bool = bool(input.get("run_in_background", False))
        label: str = input.get("description") or f"$ {command[:60]}"

        # Safety check
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                return ToolResult.error(f"Blocked command pattern: {blocked!r}")

        if run_in_background:
            return await self._launch_background(command, label, ctx)

        return await self._run_foreground(command, label, timeout, ctx)

    # ── Explicit background launch ────────────────────────────────────────────

    async def _launch_background(
        self, command: str, label: str, ctx: ToolContext
    ) -> ToolResult:
        task_id = REGISTRY.new_id()
        bg = BackgroundTask(task_id=task_id, kind="bash", label=label)
        REGISTRY.register(bg)

        async def _collect() -> None:
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=ctx.working_directory,
                    env={**os.environ, "TERM": "dumb"},
                )
                bg._process = proc
                stdout, _ = await proc.communicate()
                output = _truncate(stdout.decode("utf-8", errors="replace"))
                bg.output = output
                bg.exit_code = proc.returncode or 0
                bg.status = "failed" if bg.exit_code != 0 else "completed"
            except asyncio.CancelledError:
                bg.status = "cancelled"
            except Exception as exc:
                bg.output = f"Error: {exc}"
                bg.status = "failed"
            finally:
                import time
                bg.ended_at = time.monotonic()

        atask = asyncio.create_task(_collect())
        bg._asyncio_task = atask

        return ToolResult.ok(
            f"Background task started.\ntask_id: {task_id}\n"
            f"Use TaskOutput with id={task_id} to retrieve the result.",
            f"bg:{task_id} launched — {label[:60]}",
        )

    # ── Foreground with auto-background at 15 s ───────────────────────────────

    async def _run_foreground(
        self, command: str, label: str, timeout: int, ctx: ToolContext
    ) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ctx.working_directory,
                env={**os.environ, "TERM": "dumb"},
            )
        except Exception as e:
            return ToolResult.error(f"Failed to run command: {e}")

        # Wait up to AUTO_BG_THRESHOLD seconds
        if _should_auto_bg(command):
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=AUTO_BG_THRESHOLD
                )
                # Finished within threshold — return normally
                return self._make_result(
                    stdout.decode("utf-8", errors="replace"),
                    proc.returncode or 0,
                    command,
                )
            except asyncio.TimeoutError:
                # Still running — promote to background
                return await self._promote_to_background(proc, command, label, timeout, ctx)
        else:
            # Non-auto-bg commands: block up to the full timeout
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult.error(f"Command timed out after {timeout}s")
            return self._make_result(
                stdout.decode("utf-8", errors="replace"),
                proc.returncode or 0,
                command,
            )

    async def _promote_to_background(
        self,
        proc: asyncio.subprocess.Process,  # type: ignore[name-defined]
        command: str,
        label: str,
        timeout: int,
        ctx: ToolContext,
    ) -> ToolResult:
        task_id = REGISTRY.new_id()
        bg = BackgroundTask(task_id=task_id, kind="bash", label=label, _process=proc)
        REGISTRY.register(bg)

        remaining = max(1, timeout - AUTO_BG_THRESHOLD)

        async def _collect() -> None:
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=remaining)
                output = _truncate(stdout.decode("utf-8", errors="replace"))
                bg.output = output
                bg.exit_code = proc.returncode or 0
                bg.status = "failed" if bg.exit_code != 0 else "completed"
            except asyncio.TimeoutError:
                proc.kill()
                bg.output = f"Command killed after {timeout}s total timeout."
                bg.exit_code = -1
                bg.status = "failed"
            except asyncio.CancelledError:
                proc.kill()
                bg.status = "cancelled"
            except Exception as exc:
                bg.output = f"Error: {exc}"
                bg.status = "failed"
            finally:
                import time
                bg.ended_at = time.monotonic()

        atask = asyncio.create_task(_collect())
        bg._asyncio_task = atask

        return ToolResult.ok(
            f"Command ran for {AUTO_BG_THRESHOLD}s without finishing — moved to background.\n"
            f"task_id: {task_id}\n"
            f"Use TaskOutput with id={task_id} to retrieve the result when it completes.",
            f"bg:{task_id} auto-promoted — {label[:60]}",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_result(output: str, exit_code: int, command: str) -> ToolResult:
        output = _truncate(output)
        if exit_code != 0:
            return ToolResult(
                output=output,
                is_error=True,
                summary=f"Exit {exit_code}: {command[:60]}",
            )
        summary = f"$ {command[:60]}" + (" …" if len(command) > 60 else "")
        return ToolResult.ok(output or "(no output)", summary)
