"""
Integration test: end-to-end tool call with Gemma 4 E2B.

Tests that the orchestrator correctly:
  1. Parses a <tool_use> block from the model's output
  2. Emits tool_start / tool_end events to the UI
  3. Executes the tool (Write) and creates the file on disk

Run from the cyberpaw/agent directory:
    ../tests/run_integration.sh
or directly:
    PYTHONPATH=. python ../tests/test_integration_tool_call.py

Requires: llama-cpp-python installed, model at ~/models/cyberpaw/gemma-4-E2B-it-Q4_K_M.gguf
Working directory: ~/Downloads/temp  (created if absent)
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

# ── Path setup ────────────────────────────────────────────────────────────────
AGENT_DIR = os.path.join(os.path.dirname(__file__), "..", "agent")
sys.path.insert(0, os.path.abspath(AGENT_DIR))

MODEL_PATH = os.path.expanduser("~/models/cyberpaw/gemma-4-E2B-it-Q4_K_M.gguf")
WORK_DIR = os.path.expanduser("~/Downloads/temp")
TARGET_FILE = os.path.join(WORK_DIR, "README.md")


# ── Helpers ───────────────────────────────────────────────────────────────────

class EventCapture:
    """Collects all emitted events for assertions."""

    def __init__(self):
        self.events: list[dict] = []
        self.tokens: list[str] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)
        if event.get("type") == "token":
            self.tokens.append(event.get("text", ""))

    def of_type(self, t: str) -> list[dict]:
        return [e for e in self.events if e.get("type") == t]

    def full_text(self) -> str:
        return "".join(self.tokens)


def _cleanup():
    if os.path.exists(TARGET_FILE):
        os.remove(TARGET_FILE)


# ── Test ──────────────────────────────────────────────────────────────────────

async def run_test() -> None:
    from backends.llamacpp_backend import LlamaCppBackend
    from backends.base import GenerateParams
    from harness.orchestrator import Orchestrator
    from harness.permissions import PermissionMode
    from harness.tool_registry import ToolRegistry
    from prompt.system_prompt import build_system_prompt
    from tools import ReadTool, WriteTool, GlobTool, GrepTool, ListDirTool

    print(f"Model:      {MODEL_PATH}")
    print(f"Work dir:   {WORK_DIR}")
    print(f"Target:     {TARGET_FILE}")
    print()

    # ── Pre-conditions ────────────────────────────────────────────────────────
    assert os.path.isfile(MODEL_PATH), f"Model not found: {MODEL_PATH}"
    os.makedirs(WORK_DIR, exist_ok=True)
    _cleanup()
    assert not os.path.exists(TARGET_FILE), "Target file should not exist before test"

    # ── Load backend ──────────────────────────────────────────────────────────
    print("Loading model...", flush=True)
    t0 = time.time()
    backend = LlamaCppBackend(n_ctx=4096, n_gpu_layers=-1)
    await backend.load(MODEL_PATH, lambda p: print(f"  {p}%", end="\r", flush=True))
    print(f"\nModel loaded in {time.time() - t0:.1f}s")

    # ── Build registry ────────────────────────────────────────────────────────
    registry = ToolRegistry()
    for tool in [ReadTool(), WriteTool(), GlobTool(), GrepTool(), ListDirTool()]:
        registry.register(tool)

    # ── Capture events ────────────────────────────────────────────────────────
    capture = EventCapture()

    # ── Build orchestrator ────────────────────────────────────────────────────
    orchestrator = Orchestrator(
        backend=backend,
        registry=registry,
        system_prompt=build_system_prompt(WORK_DIR),
        working_directory=WORK_DIR,
        permission_mode=PermissionMode.AUTO_ALL,
        emit_fn=capture,
        generate_params=GenerateParams(max_new_tokens=400),
        context_size=4096,
    )

    # ── Run ───────────────────────────────────────────────────────────────────
    print("\nSending: 'Create a file README.md with the content \"hello world\"'")
    print("-" * 60)
    t1 = time.time()
    await orchestrator.handle_input(
        'Create a file README.md with the content "hello world"'
    )
    elapsed = time.time() - t1
    print(f"\n[done in {elapsed:.1f}s]")
    print("-" * 60)

    # ── Print event log ───────────────────────────────────────────────────────
    print("\n=== EVENT LOG ===")
    for e in capture.events:
        t = e.get("type")
        if t == "token":
            continue  # too noisy
        print(f"  {e}")

    print("\n=== STREAMED TEXT ===")
    print(capture.full_text() or "(none)")

    # ── Assertions ────────────────────────────────────────────────────────────
    print("\n=== ASSERTIONS ===")
    failures = []

    tool_starts = capture.of_type("tool_start")
    tool_ends   = capture.of_type("tool_end")
    errors      = capture.of_type("error")

    # 1. At least one tool_start was emitted
    if not tool_starts:
        failures.append("FAIL: no tool_start event emitted (model did not call any tool)")
    else:
        write_starts = [e for e in tool_starts if e.get("tool") == "Write"]
        if not write_starts:
            names = [e.get("tool") for e in tool_starts]
            failures.append(f"FAIL: Write tool was not called (got: {names})")
        else:
            print(f"  PASS: tool_start(Write) emitted: {write_starts[0]}")

    # 2. Matching tool_end emitted
    if tool_starts and not tool_ends:
        failures.append("FAIL: tool_start emitted but no tool_end")
    elif tool_ends:
        write_ends = [e for e in tool_ends if e.get("tool") == "Write"]
        if write_ends:
            end = write_ends[0]
            if end.get("is_error"):
                failures.append(f"FAIL: Write tool returned an error: {end}")
            else:
                print(f"  PASS: tool_end(Write) emitted without error")

    # 3. File actually exists on disk
    if not os.path.exists(TARGET_FILE):
        failures.append(f"FAIL: {TARGET_FILE} was not created on disk")
    else:
        content = open(TARGET_FILE).read()
        print(f"  PASS: {TARGET_FILE} exists, content: {content!r}")

    # 4. No unexpected errors
    if errors:
        failures.append(f"FAIL: error events emitted: {errors}")
    else:
        print(f"  PASS: no error events")

    # ── Result ────────────────────────────────────────────────────────────────
    print()
    if failures:
        print("RESULT: FAILED")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("RESULT: PASSED")


if __name__ == "__main__":
    asyncio.run(run_test())
