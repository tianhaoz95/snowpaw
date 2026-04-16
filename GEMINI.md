# CyberPaw — Gemini CLI Context

CyberPaw is a fully local, all-in-one coding agent desktop application. It provides a terminal-based interface (similar to Claude Code) but runs entirely offline using local LLMs (Gemma 4 MoE) via a Python sidecar.

## Project Overview

- **Vision:** A private-by-default coding assistant that requires no API keys and runs on local hardware.
- **Architecture:** 
    - **Frontend:** React + TypeScript + Vite, using `xterm.js` for the terminal UI.
    - **Native Shell:** Tauri (Rust) manages the window, configuration persistence, and the sidecar lifecycle.
    - **Sidecar:** A Python process (`cyberpaw-agent`) that hosts the agent harness and LLM backends.
    - **Communication:** Newline-delimited JSON (NDJSON) over standard I/O (stdin/stdout).
- **LLM Backends:**
    - `llama.cpp`: High-performance GGUF inference (recommended for 16GB+ RAM).
    - `AirLLM`: Layer-by-layer inference for memory-constrained environments (works on 8GB RAM).

## Key Components & Files

- `agent/`: The Python sidecar source code.
    - `main.py`: Entry point and NDJSON loop.
    - `harness/`: The orchestrator, message types, and permission manager.
    - `tools/`: Implementation of agent tools (Read, Write, Edit, Bash, etc.).
    - `backends/`: Abstractions for `llama.cpp` and `AirLLM`.
- `src/`: The React frontend.
    - `components/Terminal.tsx`: The primary `xterm.js` interface.
    - `hooks/useAgent.ts`: Manages the IPC bridge to the Tauri core.
- `src-tauri/`: Native Rust code.
    - `src/sidecar.rs`: Handles spawning and communicating with the Python sidecar.
- `design/`: Documentation.
    - `DESIGN.md`: Detailed architectural specification and protocol definitions.

## Building and Running

### Development Setup

1.  **Python Dependencies:**
    ```bash
    cd agent
    pip install -r requirements.txt
    ```
2.  **Frontend Dependencies:**
    ```bash
    npm install
    ```
3.  **Sidecar Binary:**
    The sidecar must be built and placed in `src-tauri/binaries/` for Tauri to find it.
    ```bash
    ./scripts/build-sidecar.sh
    ```
4.  **Run Application:**
    ```bash
    npm run tauri dev
    ```

### Model Setup
CyberPaw does not ship with model weights. Use the built-in downloader or run:
```bash
./scripts/download-model.sh
```

## Development Conventions

- **Sidecar Protocol:** All communication between the frontend and the agent is via NDJSON. 
    - **Tauri to Sidecar:** `{"type": "input", "text": "..."}`
    - **Sidecar to Tauri:** `{"type": "token", "text": "..."}`
- **Tool Implementation:** To add a new capability, create a new class in `agent/tools/` inheriting from `Tool` and register it in `agent/main.py`.
- **Permissions:** Tools are classified as "read-only" or "modifying". Modifying tools (Write, Bash, etc.) respect the `PermissionMode` (Ask, Auto-Read, Auto-All).
- **Sub-Agents:** The `Agent` tool allows the orchestrator to spawn nested agents for sub-tasks.

## Testing
- Integration tests for tool calls are located in `tests/test_integration_tool_call.py`.
- Python-specific tests can be run with `pytest` in the `agent/` directory.
