"""Tool: Sleep — pause execution for a given number of seconds."""

from __future__ import annotations

import asyncio

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_SLEEP_SECONDS = 300  # 5 minutes hard cap


class SleepTool(Tool):
    name = "Sleep"
    description = (
        "Pause execution for a specified number of seconds. "
        "Useful for waiting between retries, polling loops, or rate-limit back-off. "
        f"Maximum sleep duration is {MAX_SLEEP_SECONDS} seconds."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "number",
                "description": f"Duration to sleep in seconds (max {MAX_SLEEP_SECONDS}).",
            },
        },
        "required": ["seconds"],
    }

    def is_read_only(self, input: dict) -> bool:
        return True  # no side-effects; auto-approve in AUTO_READ mode

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        seconds = float(input["seconds"])
        if seconds <= 0:
            return ToolResult.ok("0s elapsed.", "Sleep 0s")
        if seconds > MAX_SLEEP_SECONDS:
            return ToolResult.error(
                f"Requested sleep of {seconds}s exceeds maximum of {MAX_SLEEP_SECONDS}s."
            )

        await asyncio.sleep(seconds)
        summary = f"Slept {seconds:g}s"
        return ToolResult.ok(f"Slept for {seconds:g} seconds.", summary)
