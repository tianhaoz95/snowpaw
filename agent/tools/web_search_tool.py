"""Tool: WebSearch — search the web via DuckDuckGo (no API key required)."""

from __future__ import annotations

import html
import re
import urllib.parse

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_RESULTS = 10
DEFAULT_TIMEOUT = 20  # seconds

# DuckDuckGo HTML search endpoint — no JS, no API key, scrape-friendly
_DDG_URL = "https://html.duckduckgo.com/html/"


def _parse_ddg_html(html_text: str) -> list[dict]:
    """
    Extract search results from DuckDuckGo's HTML-only page.
    Returns a list of {title, url, snippet} dicts.
    """
    results: list[dict] = []

    # Each result is in a <div class="result"> block
    # Title link: <a class="result__a" href="...">title</a>
    # Snippet:    <a class="result__snippet">...</a>
    # DDG wraps the real URL in a redirect; we extract the uddg= param.

    title_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_re = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    titles = title_re.findall(html_text)
    snippets = [m for m in snippet_re.findall(html_text)]

    for i, (raw_href, raw_title) in enumerate(titles):
        if len(results) >= MAX_RESULTS:
            break

        # Unwrap DDG redirect URL
        url = raw_href
        if "uddg=" in raw_href:
            m = re.search(r"uddg=([^&]+)", raw_href)
            if m:
                url = urllib.parse.unquote(m.group(1))

        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        title = html.unescape(title)

        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            snippet = html.unescape(snippet)

        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})

    return results


def _format_results(results: list[dict], query: str) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")
    lines.append("Sources:")
    for r in results:
        lines.append(f"- [{r['title']}]({r['url']})")
    return "\n".join(lines)


class WebSearchTool(Tool):
    name = "WebSearch"
    description = (
        "Search the web using DuckDuckGo. No API key required. "
        "Returns titles, URLs, and snippets for the top results. "
        "Use WebFetch to retrieve the full content of a specific result. "
        "Requires network access to be enabled in Settings."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "num_results": {
                "type": "integer",
                "description": f"Number of results to return (max {MAX_RESULTS}). Default: 5.",
            },
        },
        "required": ["query"],
    }

    def is_read_only(self, input: dict) -> bool:
        return False  # network call; always requires permission

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        if not ctx.network_enabled:
            return ToolResult.error(
                "Network access is disabled. Enable it in Settings → Allow network access."
            )

        query: str = input["query"].strip()
        num = min(int(input.get("num_results", 5)), MAX_RESULTS)
        timeout: int = DEFAULT_TIMEOUT

        if not query:
            return ToolResult.error("Query must not be empty.")

        try:
            import httpx
        except ImportError:
            return ToolResult.error("httpx is not installed. Run: pip install httpx")

        params = {"q": query, "kl": "us-en"}
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                },
            ) as client:
                response = await client.post(_DDG_URL, data=params)
        except httpx.TimeoutException:
            return ToolResult.error(f"Search timed out after {timeout}s.")
        except httpx.RequestError as e:
            return ToolResult.error(f"Search request failed: {e}")

        if response.status_code >= 400:
            return ToolResult.error(f"DuckDuckGo returned HTTP {response.status_code}.")

        results = _parse_ddg_html(response.text)
        results = results[:num]
        output = _format_results(results, query)

        summary = f'"{query}" → {len(results)} result(s)'
        return ToolResult.ok(output, summary)
