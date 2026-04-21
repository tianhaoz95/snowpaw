"""
CyberPaw Agent — Sidecar Entry Point
=====================================
Reads NDJSON commands from stdin, runs the agent harness, and writes
NDJSON events to stdout.  This process is spawned by Tauri as a sidecar
and communicates over a pipe.

Protocol (NDJSON)
-----------------
Tauri → Agent:
  {"type": "input", "text": "..."}
  {"type": "cd", "path": "..."}
  {"type": "reset"}
  {"type": "interrupt"}
  {"type": "config", "patch": {...}}
  {"type": "load_model", "model_path": "...", "backend": "auto|llamacpp"}
  {"type": "status_request"}
  {"type": "resume", "session_id": "..."}
  {"type": "consolidate"}

Agent → Tauri:
  {"type": "token", "text": "..."}
  {"type": "tool_start", "id": "...", "tool": "...", "input": {...}}
  {"type": "tool_end", "id": "...", "tool": "...", "summary": "...", "is_error": false}
  {"type": "status", "phase": "idle|thinking|tool_running", "turn": 1, "max_turns": 40}
  {"type": "generation_stats", "tokens": 0, "elapsed_ms": 0, "tokens_per_sec": 0.0}
  {"type": "model_progress", "stage": "loading|ready", "pct": 0}
  {"type": "model_status", "backend": "...", "loaded": true, "vram_used_mb": 0}
  {"type": "system", "text": "..."}
  {"type": "error", "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid as _uuid

# Add the current directory to sys.path so we can import from harness/ etc.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backends.selector import BackendKind, select_backend
from harness.orchestrator import Orchestrator
from harness.memory import consolidate_session_memory
from harness.permissions import PermissionMode
from harness.tool_registry import ToolRegistry
from prompt.system_prompt import build_system_prompt
from tools.read_tool import ReadTool
from tools.write_tool import WriteTool
from tools.edit_tool import EditTool
from tools.multi_edit_tool import MultiEditTool
from tools.delete_tool import DeleteFileTool
from tools.move_tool import MoveTool
from tools.bash_tool import BashTool
from tools.grep_tool import GrepTool
from tools.glob_tool import GlobTool
from tools.list_dir_tool import ListDirTool
from tools.web_search_tool import WebSearchTool
from tools.web_fetch_tool import WebFetchTool
from tools.playwright_tool import PlaywrightTool
from tools.repl_tool import ReplTool
from tools.agent_tool import AgentTool
from tools.task_tools import (
    TodoWriteTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    TaskStopTool,
    TaskOutputTool,
    reset_task_session,
)
from tools.sleep_tool import SleepTool

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("cyberpaw-agent")


# ── NDJSON helpers ────────────────────────────────────────────────────────────

def emit(event: dict) -> None:
    """Write an NDJSON event to stdout."""
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _model_temperature(path: str) -> float:
    """Return recommended temperature for the model family."""
    p = path.lower()
    if "gemma" in p:
        return 0.0  # Gemma is best at 0.0 for coding
    return 0.2      # reasonable default


async def _run_shell(command: str, cwd: str) -> None:
    """Run a shell command and emit the output as a system message."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode().strip()
        err = stderr.decode().strip()
        if out:
            emit({"type": "system", "text": out})
        if err:
            emit({"type": "system", "text": f"Error: {err}"})
    except Exception as e:
        emit({"type": "error", "message": f"Shell error: {e}"})


def _apply_config_patch(patch: dict, orchestrator: Orchestrator) -> None:
    """Apply config updates from the frontend."""
    if "permission_mode" in patch:
        try:
            mode = PermissionMode(patch["permission_mode"])
            orchestrator._permission_mode = mode
        except ValueError:
            pass

    if "max_new_tokens" in patch:
        try:
            orchestrator._params.max_new_tokens = int(patch["max_new_tokens"])
        except (ValueError, TypeError):
            pass

    if "network_enabled" in patch:
        orchestrator._network_enabled = bool(patch["network_enabled"])


# ── Main Event Loop ───────────────────────────────────────────────────────────

async def main() -> None:
    # ── Initial State ─────────────────────────────────────────────────────────
    working_directory = os.getcwd()
    context_size = 8192
    model_path = os.environ.get("CYBERPAW_MODEL_PATH")
    backend_kind = BackendKind.AUTO

    # ── Tool Setup ────────────────────────────────────────────────────────────
    registry = ToolRegistry()
    
    # 1. Base tools
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(MultiEditTool())
    registry.register(DeleteFileTool())
    registry.register(MoveTool())
    registry.register(BashTool())
    registry.register(GrepTool())
    registry.register(GlobTool())
    registry.register(ListDirTool())
    registry.register(SleepTool())
    
    # 2. Web tools
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(PlaywrightTool())

    # 3. Task & Project Management tools
    registry.register(TodoWriteTool())
    registry.register(TaskCreateTool())
    registry.register(TaskGetTool())
    registry.register(TaskListTool())
    registry.register(TaskUpdateTool())
    registry.register(TaskStopTool())
    registry.register(TaskOutputTool())

    # ── Backend Setup ─────────────────────────────────────────────────────────
    backend = select_backend(backend_kind, n_ctx=context_size, model_path=model_path)
    
    # 4. Complex tools (requiring backend/registry access)
    repl_tool = ReplTool()
    registry.register(repl_tool)
    registry.register(AgentTool(backend, registry, emit))

    # ── Session ID (used to key per-session state like REPL namespaces) ──────────
    session_id = _uuid.uuid4().hex

    # ── Orchestrator Setup ────────────────────────────────────────────────────
    system_prompt = build_system_prompt()
    orchestrator = Orchestrator(
        backend=backend,
        registry=registry,
        system_prompt=system_prompt,
        working_directory=working_directory,
        permission_mode=PermissionMode.ASK,
        emit_fn=emit,
        context_size=context_size,
        session_id=session_id,
        network_enabled=False,
    )

    if backend.is_loaded() and model_path:
        orchestrator._params.temperature = _model_temperature(model_path)

    emit({"type": "status", "phase": "idle"})

    # ── Active task handle (for interruption) ─────────────────────────────────
    current_task: asyncio.Task | None = None

    # ── Stdin reader ──────────────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    log.info("CyberPaw agent ready (backend=%s)", backend.name)

    while True:
        try:
            raw = await reader.readline()
        except Exception:
            break
        if not raw:
            break

        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from stdin: %r", line)
            continue

        msg_type = msg.get("type", "")

        if msg_type == "input":
            text = msg.get("text", "").strip()
            if not text:
                continue
            if not backend.is_loaded():
                emit({"type": "error", "message": "Model not loaded yet."})
                continue
            current_task = asyncio.create_task(orchestrator.handle_input(text))

        elif msg_type == "shell":
            command = msg.get("command", "").strip()
            if command:
                asyncio.create_task(_run_shell(command, working_directory))

        elif msg_type == "cd":
            path = os.path.expanduser(msg.get("path", "~"))
            if os.path.isdir(path):
                working_directory = path
                orchestrator.set_working_directory(path)
                emit({"type": "system", "text": f"Working directory: {path}"})
            else:
                emit({"type": "error", "message": f"Directory not found: {path}"})

        elif msg_type == "reset":
            if current_task and not current_task.done():
                current_task.cancel()
            
            # Consolidate memory before resetting (Gap 14)
            asyncio.create_task(consolidate_session_memory(
                messages=orchestrator._messages,
                backend=backend,
                registry=orchestrator._registry,
                working_directory=working_directory,
                permission_mode=orchestrator._permission_mode,
                emit_fn=emit,
                session_id=orchestrator._session_id,
            ))

            repl_tool.reset_session(orchestrator._session_id)
            reset_task_session(orchestrator._session_id)
            orchestrator.reset()
            # Rotate session ID
            session_id = _uuid.uuid4().hex
            orchestrator._session_id = session_id
            emit({"type": "system", "text": "Session reset."})
            emit({"type": "status", "phase": "idle"})

        elif msg_type == "interrupt":
            orchestrator.interrupt()
            if current_task and not current_task.done():
                current_task.cancel()

        elif msg_type == "resume":
            sess_id = msg.get("session_id")
            if sess_id:
                if orchestrator.load_session(sess_id):
                    repl_tool.reset_session(sess_id)
                    reset_task_session(sess_id)
                    session_id = sess_id
                    emit({"type": "system", "text": f"Resumed session {sess_id}."})
                else:
                    emit({"type": "error", "message": f"Could not resume session {sess_id}."})
            else:
                emit({"type": "error", "message": "No session_id provided for resume."})

        elif msg_type == "consolidate":
            asyncio.create_task(consolidate_session_memory(
                messages=orchestrator._messages,
                backend=backend,
                registry=orchestrator._registry,
                working_directory=working_directory,
                permission_mode=orchestrator._permission_mode,
                emit_fn=emit,
                session_id=orchestrator._session_id,
            ))
            emit({"type": "system", "text": "Memory consolidation started in background."})

        elif msg_type == "tool_ack":
            request_id = msg.get("id", "")
            decision = msg.get("decision", "deny")
            orchestrator.resolve_permission(request_id, decision == "allow")

        elif msg_type == "config":
            patch = msg.get("patch", {})
            _apply_config_patch(patch, orchestrator)
            if "context_size" in patch:
                try:
                    context_size = int(patch["context_size"])
                except (ValueError, TypeError):
                    pass

        elif msg_type == "status_request":
            try:
                breakdown = getattr(backend, "memory_breakdown_mb", lambda: {})()
            except Exception:
                breakdown = {}
            emit({
                "type": "model_status",
                "backend": backend.name,
                "loaded": backend.is_loaded(),
                "vram_used_mb": breakdown.get("total_mb", backend.vram_used_mb() if hasattr(backend, "vram_used_mb") else 0),
                "model_size_mb": breakdown.get("model_mb", 0),
                "kv_cache_mb": breakdown.get("kv_mb", 0),
            })

        elif msg_type == "load_model":
            new_path = os.path.expanduser(msg.get("model_path", ""))
            new_backend_str = msg.get("backend", "")
            if new_path:
                model_path = new_path
            if new_backend_str:
                try:
                    backend_kind = BackendKind(new_backend_str)
                except ValueError:
                    log.warning("Invalid backend requested: %s", new_backend_str)

            # Update backend
            old_backend = backend
            new_backend = select_backend(backend_kind, n_ctx=context_size, model_path=model_path)
            
            if new_backend != old_backend:
                backend = new_backend
                orchestrator._backend = backend
                # Re-register tools that need the backend
                registry.register(AgentTool(backend, registry, emit))

            async def _do_load():
                try:
                    await backend.load(model_path, lambda p: emit({"type": "model_progress", "pct": p}))
                    orchestrator._params.temperature = _model_temperature(model_path)
                    emit({"type": "model_status", "loaded": True, "backend": backend.name})
                except Exception as e:
                    emit({"type": "error", "message": f"Failed to load model: {e}"})

            asyncio.create_task(_do_load())


if __name__ == "__main__":
    asyncio.run(main())
