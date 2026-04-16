"""Tool: WebFetch — fetch a URL and return its content as plain text / markdown."""

from __future__ import annotations

import html.parser
import re
import textwrap
from typing import TYPE_CHECKING

from harness.tool_registry import Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    pass

MAX_RESPONSE_CHARS = 40_000
DEFAULT_TIMEOUT = 30  # seconds


# ── Minimal HTML → markdown converter (stdlib only) ───────────────────────────

class _HTMLToText(html.parser.HTMLParser):
    """
    Strips HTML tags and converts common elements to readable plain text.
    No external dependencies — uses only html.parser from the stdlib.
    """

    _SKIP_TAGS = frozenset(["script", "style", "noscript", "head", "meta", "link"])
    _BLOCK_TAGS = frozenset([
        "p", "div", "section", "article", "main", "header", "footer",
        "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "code", "hr",
    ])
    _HEADING_TAGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._current_tag = ""
        self._href: str | None = None
        self._pending_heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth > 0:
            self._skip_depth += 1
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth = 1
            return
        self._current_tag = tag
        attr_dict = dict(attrs)
        if tag in self._HEADING_TAGS:
            self._pending_heading = self._HEADING_TAGS[tag]
            self._parts.append("\n\n")
        elif tag == "a":
            self._href = attr_dict.get("href")
        elif tag == "img":
            alt = attr_dict.get("alt", "")
            src = attr_dict.get("src", "")
            if alt:
                self._parts.append(f"[{alt}]({src})")
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag in ("br",):
            self._parts.append("\n")
        elif tag in ("p", "div", "section", "article", "blockquote"):
            self._parts.append("\n\n")
        elif tag == "pre":
            self._parts.append("\n```\n")
        elif tag == "hr":
            self._parts.append("\n---\n")
        elif tag == "strong" or tag == "b":
            self._parts.append("**")
        elif tag == "em" or tag == "i":
            self._parts.append("_")
        elif tag == "code" and self._current_tag != "pre":
            self._parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in self._HEADING_TAGS:
            self._parts.append("\n\n")
            self._pending_heading = None
        elif tag == "a" and self._href:
            self._parts.append(f"({self._href})")
            self._href = None
        elif tag == "pre":
            self._parts.append("\n```\n")
        elif tag in ("p", "div", "section", "article"):
            self._parts.append("\n\n")
        elif tag == "strong" or tag == "b":
            self._parts.append("**")
        elif tag == "em" or tag == "i":
            self._parts.append("_")
        elif tag == "code" and tag != "pre":
            self._parts.append("`")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data
        if self._pending_heading:
            text = f"{self._pending_heading} {text.strip()}"
            self._pending_heading = None
        elif self._href:
            text = f"[{text}]"
        self._parts.append(text)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse excessive blank lines
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        # Strip leading/trailing whitespace per line
        lines = [line.rstrip() for line in raw.splitlines()]
        return "\n".join(lines).strip()


def _html_to_markdown(html_text: str) -> str:
    parser = _HTMLToText()
    try:
        parser.feed(html_text)
        return parser.get_text()
    except Exception:
        # Fallback: strip all tags with regex
        return re.sub(r"<[^>]+>", " ", html_text)


# ── Tool ──────────────────────────────────────────────────────────────────────

class WebFetchTool(Tool):
    name = "WebFetch"
    description = (
        "Fetch a URL and return its content as readable text. "
        "HTML pages are converted to markdown. "
        "JSON and plain-text responses are returned as-is. "
        "Requires network access to be enabled in Settings."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (http:// or https://).",
            },
            "prompt": {
                "type": "string",
                "description": "Optional: what information to extract from the page (used as a hint in the summary).",
            },
            "timeout": {
                "type": "integer",
                "description": f"Request timeout in seconds. Default: {DEFAULT_TIMEOUT}.",
            },
        },
        "required": ["url"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False  # network call; always requires permission

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        if not ctx.network_enabled:
            return ToolResult.error(
                "Network access is disabled. Enable it in Settings → Allow network access."
            )

        url: str = input["url"].strip()
        timeout: int = int(input.get("timeout", DEFAULT_TIMEOUT))

        if not url.startswith(("http://", "https://")):
            return ToolResult.error(f"Invalid URL (must start with http:// or https://): {url}")

        try:
            import httpx
        except ImportError:
            return ToolResult.error("httpx is not installed. Run: pip install httpx")

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "SnowPaw/1.0 (local AI assistant)"},
            ) as client:
                response = await client.get(url)
        except httpx.TimeoutException:
            return ToolResult.error(f"Request timed out after {timeout}s: {url}")
        except httpx.RequestError as e:
            return ToolResult.error(f"Request failed: {e}")

        if response.status_code >= 400:
            return ToolResult.error(
                f"HTTP {response.status_code} from {url}"
            )

        content_type = response.headers.get("content-type", "")
        raw = response.text

        if "html" in content_type:
            body = _html_to_markdown(raw)
        else:
            body = raw  # JSON, plain text, etc.

        if len(body) > MAX_RESPONSE_CHARS:
            half = MAX_RESPONSE_CHARS // 2
            body = (
                body[:half]
                + f"\n\n… [{len(body) - MAX_RESPONSE_CHARS} chars truncated] …\n\n"
                + body[-half:]
            )

        hint = input.get("prompt", "")
        summary = f"Fetched {url}" + (f" — {hint[:40]}" if hint else "")
        return ToolResult.ok(body or "(empty response)", summary)
