"""Tool: Playwright — control a headless browser."""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Literal

from harness.tool_registry import Tool, ToolContext, ToolResult

# Action types
Action = Literal["goto", "click", "fill", "press", "screenshot", "get_content", "evaluate"]

MAX_CONTENT_CHARS = 30_000
DEFAULT_TIMEOUT = 30000  # ms (Playwright uses ms)


class PlaywrightTool(Tool):
    name = "Playwright"
    description = (
        "Control a headless browser to interact with web pages. "
        "Can navigate to URLs, click elements, fill forms, and take screenshots. "
        "Requires network access to be enabled for external URLs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["goto", "click", "fill", "press", "screenshot", "get_content", "evaluate"],
                "description": "The action to perform in the browser.",
            },
            "url": {
                "type": "string",
                "description": "The URL to navigate to (required for 'goto').",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for the element to interact with (required for 'click', 'fill', 'press').",
            },
            "value": {
                "type": "string",
                "description": "Value to fill into an input field (required for 'fill').",
            },
            "key": {
                "type": "string",
                "description": "Key to press, e.g., 'Enter', 'Tab' (required for 'press').",
            },
            "expression": {
                "type": "string",
                "description": "JavaScript expression to evaluate (required for 'evaluate').",
            },
            "wait_until": {
                "type": "string",
                "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                "default": "load",
                "description": "When to consider the navigation successful.",
            },
        },
        "required": ["action"],
    }

    def is_read_only(self, input: dict) -> bool:
        # Browser interactions are stateful and touch the network
        return False

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        action: Action = input["action"]
        url: str | None = input.get("url")

        # Network check for non-local URLs
        if url and not url.startswith(("http://localhost", "http://127.0.0.1")):
            if not ctx.network_enabled:
                return ToolResult.error(
                    "Network access is disabled. Enable it in Settings to access external URLs."
                )

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ToolResult.error("playwright is not installed. Run: pip install playwright")

        # Check if browsers are installed (simple heuristic)
        # Playwright usually puts browsers in ~/Library/Caches/ms-playwright on macOS
        # We can also just try to launch and catch the specific error.

        try:
            async with async_playwright() as p:
                try:
                    browser = await p.chromium.launch(headless=True)
                except Exception as e:
                    if "Executable doesn't exist" in str(e) or "not installed" in str(e).lower():
                        return ToolResult.error(
                            "Browser engine (Chromium) is not installed. "
                            "Please click 'Install Browser' in the application settings."
                        )
                    raise e

                page = await browser.new_page()
                page.set_default_timeout(DEFAULT_TIMEOUT)

                result_text = ""
                summary = ""

                if action == "goto":
                    if not url:
                        return ToolResult.error("URL is required for 'goto' action.")
                    await page.goto(url, wait_until=input.get("wait_until", "load"))
                    result_text = f"Navigated to {url}\nTitle: {await page.title()}"
                    summary = f"Browser: goto {url}"

                elif action == "click":
                    selector = input.get("selector")
                    if not selector:
                        return ToolResult.error("Selector is required for 'click' action.")
                    await page.click(selector)
                    result_text = f"Clicked element: {selector}"
                    summary = f"Browser: click {selector}"

                elif action == "fill":
                    selector = input.get("selector")
                    value = input.get("value")
                    if not selector or value is None:
                        return ToolResult.error("Selector and value are required for 'fill' action.")
                    await page.fill(selector, value)
                    result_text = f"Filled {selector} with '{value}'"
                    summary = f"Browser: fill {selector}"

                elif action == "press":
                    selector = input.get("selector")
                    key = input.get("key")
                    if not selector or not key:
                        return ToolResult.error("Selector and key are required for 'press' action.")
                    await page.press(selector, key)
                    result_text = f"Pressed {key} on {selector}"
                    summary = f"Browser: press {key}"

                elif action == "get_content":
                    content = await page.content()
                    # Truncate if too large
                    if len(content) > MAX_CONTENT_CHARS:
                        content = content[:MAX_CONTENT_CHARS] + "... [truncated]"
                    result_text = content
                    summary = "Browser: get_content"

                elif action == "screenshot":
                    # For now, we save to a temporary file and return the path
                    fd, path = tempfile.mkstemp(suffix=".png", prefix="cyberpaw_ss_")
                    os.close(fd)
                    await page.screenshot(path=path)
                    result_text = f"Screenshot saved to: {path}"
                    summary = "Browser: screenshot"

                elif action == "evaluate":
                    expr = input.get("expression")
                    if not expr:
                        return ToolResult.error("Expression is required for 'evaluate' action.")
                    result = await page.evaluate(expr)
                    result_text = str(result)
                    summary = "Browser: evaluate JS"

                await browser.close()
                return ToolResult.ok(result_text, summary)

        except Exception as e:
            return ToolResult.error(f"Playwright error: {e}")
