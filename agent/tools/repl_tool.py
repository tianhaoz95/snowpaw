"""Tool: REPL — persistent Python interpreter with state across calls."""

from __future__ import annotations

import asyncio
import io
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

from harness.tool_registry import Tool, ToolContext, ToolResult

MAX_OUTPUT_CHARS = 20_000


class ReplTool(Tool):
    name = "REPL"
    description = (
        "Execute Python code in a persistent interpreter. "
        "Variables, imports, and definitions survive across calls within the same session. "
        "Use this for data analysis, calculations, or iterative scripting. "
        "stdout and stderr are captured and returned. "
        "Avoid side-effects that are hard to undo (file deletions, network calls)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute.",
            },
            "description": {
                "type": "string",
                "description": "Short description of what this code does (shown in UI).",
            },
        },
        "required": ["code"],
    }

    def __init__(self) -> None:
        # session_id → namespace dict
        # Each session gets its own interpreter state.
        self._namespaces: dict[str, dict] = {}

    def is_read_only(self, input: dict) -> bool:
        return False  # code can write files, mutate state, etc.

    def _get_namespace(self, session_id: str) -> dict:
        if session_id not in self._namespaces:
            self._namespaces[session_id] = {"__name__": "__repl__", "__builtins__": __builtins__}
        return self._namespaces[session_id]

    def reset_session(self, session_id: str) -> None:
        """Clear the interpreter state for a session (called on session reset)."""
        self._namespaces.pop(session_id, None)

    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        code: str = input["code"]
        ns = self._get_namespace(ctx.session_id)

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        def _run() -> tuple[str | None, bool]:
            """Execute code, return (repr_of_last_expr_or_None, had_exception)."""
            try:
                import ast as _ast
                tree = _ast.parse(code, mode="exec")
            except SyntaxError as e:
                return None, str(e)

            # Split: if last statement is an Expr, eval it for its repr
            last_expr_repr = None
            had_error: str | None = None

            if tree.body and isinstance(tree.body[-1], _ast.Expr):
                *body_stmts, last_stmt = tree.body
                exec_tree = _ast.Module(body=body_stmts, type_ignores=[])
                eval_expr = _ast.Expression(body=last_stmt.value)
                _ast.fix_missing_locations(exec_tree)
                _ast.fix_missing_locations(eval_expr)
                try:
                    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                        exec(compile(exec_tree, "<repl>", "exec"), ns)
                        val = eval(compile(eval_expr, "<repl>", "eval"), ns)
                        if val is not None:
                            last_expr_repr = repr(val)
                except Exception:
                    had_error = traceback.format_exc()
            else:
                try:
                    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                        exec(compile(tree, "<repl>", "exec"), ns)
                except Exception:
                    had_error = traceback.format_exc()

            return last_expr_repr, had_error

        last_repr, error = await asyncio.to_thread(_run)

        stdout_out = stdout_buf.getvalue()
        stderr_out = stderr_buf.getvalue()

        parts: list[str] = []
        if stdout_out:
            parts.append(stdout_out)
        if stderr_out:
            parts.append(f"[stderr]\n{stderr_out}")
        if last_repr is not None:
            parts.append(last_repr)

        output = "\n".join(parts) if parts else "(no output)"

        if len(output) > MAX_OUTPUT_CHARS:
            half = MAX_OUTPUT_CHARS // 2
            output = (
                output[:half]
                + f"\n\n… [{len(output) - MAX_OUTPUT_CHARS} chars truncated] …\n\n"
                + output[-half:]
            )

        if isinstance(error, str):
            # Syntax error string
            return ToolResult(output=error, is_error=True, summary=f"SyntaxError in REPL")
        if error:
            return ToolResult(output=output or error, is_error=True,
                              summary="Exception in REPL")

        desc = input.get("description", "")
        summary = desc[:60] if desc else (code.split("\n")[0])[:60]
        return ToolResult.ok(output, summary)
