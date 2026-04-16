"""
CyberPaw Agent — Sidecar Entry Point
=====================================
Reads NDJSON commands from stdin, runs the agent harness, and writes
NDJSON events to stdout.  This process is spawned by Tauri as a sidecar
and communicates exclusively via stdin/stdout.

Input message types (from Tauri):
  {"type": "input",            "text": "..."}
  {"type": "cd",               "path": "..."}
  {"type": "reset"}
  {"type": "interrupt"}
  {"type": "config",           "patch": {...}}
  {"type": "tool_ack",         "id": "...", "decision": "allow"|"deny"}
  {"type": "status_request"}
  {"type": "load_model",       "model_path": "...", "backend"?: "auto"|"llamacpp"|"airllm"}
  {"type": "download_catalog"}
  {"type": "download_start",   "model_id": "...", "dest_dir": "...", "hf_token"?: "..."}
  {"type": "download_cancel"}

Output message types (to Tauri → WebView):
  {"type": "token",              "text": "..."}
  {"type": "tool_start",         "id": "...", "tool": "...", "input": {...}}
  {"type": "tool_end",           "id": "...", "tool": "...", "summary": "...", "is_error": bool}
  {"type": "tool_ask",           "id": "...", "tool": "...", "input": {...}}
  {"type": "status",             "phase": "idle"|"thinking"|"tool_running", "tool"?: "..."}
  {"type": "system",             "text": "..."}
  {"type": "error",              "message": "..."}
  {"type": "model_progress",     "stage": "loading"|"ready", "pct": int}
  {"type": "model_status",       "backend": "...", "loaded": bool}
  {"type": "download_catalog",   "models": [...]}
  {"type": "download_progress",  "model_id": "...", "pct": int, "downloaded_mb": float,
                                 "total_mb": float|null, "speed_mbps": float}
  {"type": "download_done",      "model_id": "...", "path": "..."}
  {"type": "download_error",     "model_id": "...", "message": "..."}
  {"type": "download_cancelled", "model_id": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# ── Logging: write to stderr so it doesn't pollute the stdout NDJSON stream ──
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cyberpaw.main")


def emit(event: dict) -> None:
    """Write a single NDJSON event to stdout."""
    line = json.dumps(event, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _run_shell(command: str, working_directory: str) -> None:
    """Run *command* in *working_directory*, streaming output as shell_output events."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=working_directory,
            env={**os.environ, "TERM": "dumb"},
        )
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(256)
            if not chunk:
                break
            emit({"type": "shell_output", "text": chunk.decode("utf-8", errors="replace")})
        exit_code = await proc.wait()
        emit({"type": "shell_done", "exit_code": exit_code})
    except Exception as exc:
        emit({"type": "shell_output", "text": f"Error: {exc}\n"})
        emit({"type": "shell_done", "exit_code": 1})


async def _load_model(backend, path: str) -> None:
    """Load model at *path* into *backend*, emitting progress events.

    Runs a heartbeat task in parallel that emits a pulse every second so
    the UI always shows activity even when the backend gives no ticks
    (e.g. during mmap of a large file before any tensors are loaded).
    """
    if not path or not os.path.exists(path):
        emit({"type": "error", "message": f"Model file not found: {path}"})
        return

    if backend.is_loaded():
        backend.unload()

    emit({"type": "model_progress", "stage": "loading", "pct": 0})
    emit({"type": "model_status", "backend": backend.name, "loaded": False})

    last_pct = [0]

    def _on_progress(pct: int) -> None:
        last_pct[0] = pct
        emit({"type": "model_progress", "stage": "loading", "pct": pct})

    # Heartbeat: re-emit the last known pct every second so the UI
    # animates even during silent phases (mmap, GPU transfer).
    heartbeat_stop = asyncio.Event()

    async def _heartbeat() -> None:
        while not heartbeat_stop.is_set():
            await asyncio.sleep(1.0)
            if not heartbeat_stop.is_set() and last_pct[0] < 100:
                emit({"type": "model_progress", "stage": "loading",
                      "pct": last_pct[0], "heartbeat": True})

    heartbeat_task = asyncio.create_task(_heartbeat())

    try:
        await backend.load(path, _on_progress)
        emit({"type": "model_progress", "stage": "ready", "pct": 100})
        emit({"type": "model_status", "backend": backend.name, "loaded": True})
        log.info("Model loaded: %s", path)
    except Exception as exc:
        emit({"type": "error", "message": f"Model load failed: {exc}"})
        log.exception("Model load failed")
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()


async def _install_browsers() -> None:
    """Run playwright install chromium, emitting progress."""
    emit({"type": "model_progress", "stage": "loading", "pct": 0, "text": "Installing Chromium..."})
    try:
        # Note: In a PyInstaller bundle, we can't easily use sys.executable -m
        # but we can try to call playwright.cli.main directly in a thread.
        # However, it uses synchronous blocking calls.
        # The most reliable way in a bundle is to use the 'playwright' module entry point.
        import subprocess
        import re
        
        # Heuristic: if we are in a bundle, use the same executable
        executable = sys.executable
        cmd = [executable, "-m", "playwright", "install", "chromium"]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        
        # Regex to match percentage in playwright output (e.g. "  12% ")
        pct_re = re.compile(r"(\d+)%")
        
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode().strip()
            if text:
                # Extract percentage if present, else keep last known or default to 50
                match = pct_re.search(text)
                pct = int(match.group(1)) if match else 50
                # Use a more descriptive text
                display_text = f"Installing Chromium: {text}"
                if len(display_text) > 60:
                    display_text = display_text[:57] + "..."
                
                emit({
                    "type": "model_progress", 
                    "stage": "loading", 
                    "pct": pct, 
                    "text": display_text,
                    "backend": "Browser"
                })
        
        exit_code = await proc.wait()
        if exit_code == 0:
            emit({"type": "model_progress", "stage": "ready", "pct": 100, "text": "Chromium installed."})
            emit({"type": "system", "text": "Playwright browser (Chromium) installed successfully."})
        else:
            emit({"type": "error", "message": f"Browser installation failed (exit {exit_code})."})
    except Exception as exc:
        emit({"type": "error", "message": f"Failed to install browser: {exc}"})


async def main() -> None:
    from backends import BackendKind, select_backend
    from backends.base import GenerateParams
    from harness.orchestrator import Orchestrator
    from harness.permissions import PermissionMode
    from harness.tool_registry import ToolRegistry
    from prompt.system_prompt import build_system_prompt
    from tools import (
        AgentTool, BashTool, DeleteFileTool, EditTool, GlobTool,
        GrepTool, ListDirTool, MoveTool, MultiEditTool, ReadTool,
        ReplTool, SleepTool, WebFetchTool, WebSearchTool, WriteTool,
        TodoWriteTool, PlaywrightTool,
        TaskCreateTool, TaskGetTool, TaskListTool,
        TaskUpdateTool, TaskStopTool, TaskOutputTool,
        reset_task_session,
    )

    # ── Session ID (used to key per-session state like REPL namespaces) ──────────
    import uuid as _uuid
    session_id = _uuid.uuid4().hex

    # ── Default configuration ─────────────────────────────────────────────────
    working_directory = os.path.expanduser("~")
    backend_kind = BackendKind.AUTO
    model_path = os.environ.get("CYBERPAW_MODEL_PATH", "")
    context_size = 8192
    max_new_tokens = 2048
    temperature = 0.2
    permission_mode = PermissionMode.ASK
    system_prompt_append = ""
    network_enabled = False  # opt-in; user must enable in Settings

    # ── Backend + model ───────────────────────────────────────────────────────
    backend = select_backend(backend_kind, n_ctx=context_size)
    emit({"type": "model_status", "backend": backend.name, "loaded": False})

    if model_path:
        await _load_model(backend, model_path)

    # ── Tool registry ─────────────────────────────────────────────────────────
    registry = ToolRegistry()
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(MultiEditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(BashTool())
    registry.register(ListDirTool())
    registry.register(MoveTool())
    registry.register(DeleteFileTool())
    repl_tool = ReplTool()
    registry.register(repl_tool)
    registry.register(SleepTool())
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())
    registry.register(PlaywrightTool())

    # AgentTool needs references to the backend, registry, and emit_fn
    agent_tool = AgentTool(backend=backend, registry=registry, emit_fn=emit)
    registry.register(agent_tool)

    # Task & Project Management tools
    registry.register(TodoWriteTool())
    registry.register(TaskCreateTool())
    registry.register(TaskGetTool())
    registry.register(TaskListTool())
    registry.register(TaskUpdateTool())
    registry.register(TaskStopTool())
    registry.register(TaskOutputTool())

    # ── Orchestrator ──────────────────────────────────────────────────────────
    system_prompt = build_system_prompt(
        working_directory=working_directory,
        append=system_prompt_append,
    )
    orchestrator = Orchestrator(
        backend=backend,
        registry=registry,
        system_prompt=system_prompt,
        working_directory=working_directory,
        permission_mode=permission_mode,
        emit_fn=emit,
        generate_params=GenerateParams(
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        ),
        context_size=context_size,
        session_id=session_id,
        network_enabled=network_enabled,
    )

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
            break  # EOF — Tauri closed the pipe

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
            repl_tool.reset_session(orchestrator._session_id)
            reset_task_session(orchestrator._session_id)
            orchestrator.reset()
            # Rotate session ID so the new session gets a fresh REPL namespace
            session_id = _uuid.uuid4().hex
            orchestrator._session_id = session_id
            emit({"type": "system", "text": "Session reset."})
            emit({"type": "status", "phase": "idle"})

        elif msg_type == "interrupt":
            orchestrator.interrupt()
            if current_task and not current_task.done():
                current_task.cancel()

        elif msg_type == "tool_ack":
            request_id = msg.get("id", "")
            decision = msg.get("decision", "deny")
            orchestrator.resolve_permission(request_id, decision == "allow")

        elif msg_type == "config":
            patch = msg.get("patch", {})
            _apply_config_patch(patch, orchestrator)

        elif msg_type == "status_request":
            emit({
                "type": "model_status",
                "backend": backend.name,
                "loaded": backend.is_loaded(),
                "vram_used_mb": backend.vram_used_mb(),
            })

        elif msg_type == "load_model":
            new_path = os.path.expanduser(msg.get("model_path", ""))
            new_backend_str = msg.get("backend", "")
            if new_backend_str and new_backend_str != backend_kind.value:
                # Backend type changed — swap it out
                backend_kind = BackendKind(new_backend_str)
                old_backend = backend
                backend = select_backend(backend_kind, n_ctx=context_size)
                old_backend.unload()
                # Re-wire orchestrator and agent tool to new backend
                orchestrator._backend = backend
                agent_tool._backend = backend
            if new_path:
                model_path = new_path
            asyncio.create_task(_load_model(backend, model_path))

        elif msg_type == "download_catalog":
            from downloader import get_catalog
            emit({"type": "download_catalog", "models": get_catalog()})

        elif msg_type == "download_start":
            from downloader import start_download
            model_id = msg.get("model_id", "")
            dest_dir = os.path.expanduser(
                msg.get("dest_dir") or os.path.join(os.path.expanduser("~"), "models", "cyberpaw")
            )
            hf_token = msg.get("hf_token", "")
            asyncio.create_task(
                start_download(model_id, dest_dir, emit, hf_token)
            )

        elif msg_type == "download_cancel":
            from downloader import cancel_download
            cancelled = cancel_download()
            if not cancelled:
                emit({"type": "system", "text": "No active download to cancel."})

        elif msg_type == "install_browsers":
            asyncio.create_task(_install_browsers())

        else:
            log.debug("Unknown message type: %s", msg_type)


def _apply_config_patch(patch: dict, orchestrator) -> None:
    """Apply non-model config updates from the Settings page.
    model_path and backend changes are handled by the frontend
    sending an explicit load_model message instead."""
    if "working_directory" in patch:
        path = os.path.expanduser(patch["working_directory"])
        if os.path.isdir(path):
            orchestrator.set_working_directory(path)

    if "permission_mode" in patch:
        from harness.permissions import PermissionMode
        try:
            orchestrator._permission_mode = PermissionMode(patch["permission_mode"])
        except ValueError:
            pass

    if "temperature" in patch:
        orchestrator._params.temperature = float(patch["temperature"])

    if "max_new_tokens" in patch:
        orchestrator._params.max_new_tokens = int(patch["max_new_tokens"])

    if "system_prompt_append" in patch:
        from prompt.system_prompt import build_system_prompt
        orchestrator._system_prompt = build_system_prompt(
            working_directory=orchestrator._working_directory,
            append=patch["system_prompt_append"],
        )

    if "network_enabled" in patch:
        orchestrator._network_enabled = bool(patch["network_enabled"])


if __name__ == "__main__":
    asyncio.run(main())
