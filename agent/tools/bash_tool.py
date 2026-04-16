"""Tool: Bash — run a shell command in the working directory."""

from __future__ import annotations

import asyncio
import os
import shlex

from harness.tool_registry import Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT = 120  # seconds
MAX_OUTPUT_CHARS = 50_000

# Commands that are always blocked regardless of permission mode
BLOCKED_COMMANDS = frozenset([
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
    ":(){:|:&};:", "fork bomb",
])


class BashTool(Tool):
    name = "Bash"
    description = (
        "Execute a shell command in the working directory. "
        "Output (stdout + stderr) is returned. "
        "Avoid destructive commands. Long-running commands should use a timeout."
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
                "description": f"Timeout in seconds. Default: {DEFAULT_TIMEOUT}.",
            },
            "description": {
                "type": "string",
                "description": "Short human-readable description of what this command does.",
            },
        },
        "required": ["command"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        command: str = input["command"]
        timeout: int = int(input.get("timeout", DEFAULT_TIMEOUT))

        # Basic safety check
        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                return ToolResult.error(f"Blocked command pattern: {blocked!r}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ctx.working_directory,
                env={**os.environ, "TERM": "dumb"},
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult.error(f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult.error(f"Failed to run command: {e}")

        output = stdout.decode("utf-8", errors="replace")
        if len(output) > MAX_OUTPUT_CHARS:
            half = MAX_OUTPUT_CHARS // 2
            output = (
                output[:half]
                + f"\n\n… [{len(output) - MAX_OUTPUT_CHARS} chars truncated] …\n\n"
                + output[-half:]
            )

        exit_code = proc.returncode or 0
        if exit_code != 0:
            return ToolResult(
                output=output,
                is_error=True,
                summary=f"Exit {exit_code}: {command[:60]}",
            )

        summary = f"$ {command[:60]}" + (" …" if len(command) > 60 else "")
        return ToolResult.ok(output or "(no output)", summary)
