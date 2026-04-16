# SnowPaw — Design Document

> A fully local, all-in-one coding agent desktop app.
> Tauri shell · Python sidecar · Gemma 4 (E4B MoE) · minimal multi-agent harness

---

## 1. Vision

SnowPaw is a desktop application that looks and feels like a terminal-based coding agent (similar to Claude Code) but runs **entirely offline**. No API keys, no cloud calls. The LLM is Gemma 4 E4B (a 4-billion-parameter MoE model) loaded via **AirLLM** when memory is constrained or **llama.cpp** when sufficient RAM/VRAM is available. The agent harness is a minimal Python reimplementation of the multi-agent loop observed in `./claude-code`.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Tauri Desktop App                         │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    WebView (Frontend)                      │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌───────────────┐  ┌───────────────┐   │  │
│  │  │  Terminal UI  │  │  Menu Bar     │  │  Settings     │   │  │
│  │  │  (xterm.js)  │  │  (open folder │  │  Page         │   │  │
│  │  │              │  │   model sel.) │  │               │   │  │
│  │  └──────┬───────┘  └───────────────┘  └───────────────┘   │  │
│  └─────────┼──────────────────────────────────────────────────┘  │
│            │  Tauri IPC (invoke / emit)                          │
│  ┌─────────▼──────────────────────────────────────────────────┐  │
│  │                   Tauri Rust Core                          │  │
│  │  - Sidecar lifecycle (spawn / kill / restart)              │  │
│  │  - stdin/stdout bridge to Python sidecar                   │  │
│  │  - File dialog (open folder)                               │  │
│  │  - App config persistence (tauri-plugin-store)             │  │
│  └─────────┬──────────────────────────────────────────────────┘  │
│            │  stdin/stdout (newline-delimited JSON)               │
│  ┌─────────▼──────────────────────────────────────────────────┐  │
│  │              Python Sidecar  (snowpaw-agent)               │  │
│  │                                                            │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │                  Agent Harness                       │  │  │
│  │  │  Orchestrator → Tool Executor → Sub-agent spawner    │  │  │
│  │  └──────────────────────┬───────────────────────────────┘  │  │
│  │                         │                                  │  │
│  │  ┌──────────────────────▼───────────────────────────────┐  │  │
│  │  │              LLM Backend Abstraction                  │  │  │
│  │  │                                                       │  │  │
│  │  │   ┌─────────────────┐    ┌──────────────────────┐    │  │  │
│  │  │   │  AirLLM Backend │    │  llama.cpp Backend   │    │  │  │
│  │  │   │  (layer-by-     │    │  (llama-cpp-python    │    │  │  │
│  │  │   │   layer, low    │    │   or subprocess)     │    │  │  │
│  │  │   │   VRAM)         │    │                      │    │  │  │
│  │  │   └─────────────────┘    └──────────────────────┘    │  │  │
│  │  └───────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Tauri Shell

**Role:** Thin native wrapper. Owns the window, menus, and sidecar lifecycle.

| Responsibility | Implementation |
|---|---|
| Window chrome | Tauri v2, `decorations: false`, custom title bar in WebView |
| Sidecar spawn | `tauri-plugin-shell` sidecar, binary bundled in `src-tauri/binaries/` |
| IPC bridge | `invoke()` for commands, `emit()`/`listen()` for streaming events |
| File open dialog | `tauri-plugin-dialog` → returns path → sent to sidecar |
| Config persistence | `tauri-plugin-store` → `snowpaw.conf.json` in app data dir |
| Auto-update (optional) | `tauri-plugin-updater` |

**Sidecar binary name:** `snowpaw-agent-<target-triple>` (e.g. `snowpaw-agent-aarch64-apple-darwin`).  
Built with PyInstaller or Nuitka, bundled as a Tauri external binary.

**Tauri commands (Rust → exposed to JS):**

```
send_input(text: String)         → write line to sidecar stdin
set_working_directory(path: String)
get_config() → Config
set_config(patch: ConfigPatch)
get_model_status() → ModelStatus  (backend, loaded, vram_used_mb)
interrupt()                       → sends SIGINT to sidecar
```

**Tauri events (sidecar → JS):**

```
agent://stream   { type: "token"|"tool_start"|"tool_end"|"error"|"done", ... }
agent://status   { phase: "idle"|"thinking"|"tool_running", tool?: string }
model://progress { stage: "loading"|"ready", pct: number }
```

---

### 3.2 Frontend (WebView)

**Stack:** React + TypeScript, bundled with Vite.

#### 3.2.1 Terminal UI

- **Library:** `xterm.js` with `xterm-addon-fit` (fills the window pane)
- **Rendering:** Agent token stream events are written directly to the xterm instance via `term.write()`. ANSI escape codes are used for color, bold, and cursor — matching the feel of a real terminal agent.
- **Input:** xterm's `onData` handler captures keystrokes. On Enter, the accumulated line is sent via `invoke('send_input', ...)`. Ctrl-C triggers `invoke('interrupt')`.
- **Prompt indicator:** A `>` prompt is rendered at the bottom when the agent is idle.

#### 3.2.2 Menu Bar

A narrow top bar (32px) with:

- **Open Folder** → triggers `open()` from `@tauri-apps/plugin-dialog`, sends path to sidecar
- **New Session** → clears terminal, sends `reset` command to sidecar
- **Model indicator pill** → shows current backend (AirLLM / llama.cpp) and model load state
- **Settings gear** → opens the Settings overlay

#### 3.2.3 Settings Page

A slide-in panel (not a new window) with:

| Setting | Type | Default |
|---|---|---|
| Working directory | Path picker | `~` |
| LLM backend | Radio: Auto / AirLLM / llama.cpp | Auto |
| Model path | Path picker (GGUF or HF dir) | bundled default |
| Context window | Slider 2k–32k | 8192 |
| Max new tokens | Number | 2048 |
| Temperature | Slider 0–1 | 0.2 |
| System prompt append | Textarea | empty |
| Permission mode | Radio: Ask / Auto-approve read / Auto-approve all | Ask |

---

### 3.3 Python Sidecar (`snowpaw-agent`)

The sidecar is a single Python process. It communicates with the Tauri core over **stdin/stdout** using newline-delimited JSON (NDJSON).

#### Protocol (stdin → sidecar)

```json
{"type": "input",   "text": "refactor the auth module"}
{"type": "cd",      "path": "/Users/alice/myproject"}
{"type": "reset"}
{"type": "interrupt"}
{"type": "config",  "patch": {"temperature": 0.3}}
```

#### Protocol (sidecar → stdout)

```json
{"type": "token",      "text": "Sure, let me look at"}
{"type": "tool_start", "tool": "Read", "input": {"file_path": "src/auth.py"}}
{"type": "tool_end",   "tool": "Read", "summary": "Read 142 lines"}
{"type": "tool_ask",   "tool": "Bash", "input": {"command": "pytest"}, "id": "t1"}
{"type": "tool_ack",   "id": "t1",     "decision": "allow"}
{"type": "status",     "phase": "idle"}
{"type": "error",      "message": "..."}
{"type": "model_progress", "stage": "loading", "pct": 42}
```

The Rust sidecar bridge reads stdout line by line and re-emits each parsed JSON object as a Tauri event to the WebView.

---

### 3.4 Agent Harness (Python)

Inspired by the `claude-code` source (`src/QueryEngine.ts`, `src/Task.ts`, `src/Tool.ts`, `src/tools/AgentTool/runAgent.ts`), but minimal and adapted for a local LLM.

#### 3.4.1 Core Loop

```
User input
    │
    ▼
┌──────────────────────────────────────────┐
│            Orchestrator                  │
│                                          │
│  1. Build messages list                  │
│  2. Render system prompt                 │
│  3. Call LLM (streaming)                 │
│  4. Parse response for tool calls        │
│  5. For each tool call:                  │
│     a. Check permissions                 │
│     b. Execute tool                      │
│     c. Append tool result to messages    │
│  6. If no more tool calls → emit done    │
│  7. Else → goto 3                        │
└──────────────────────────────────────────┘
```

The loop is capped at **MAX_TURNS = 40** to prevent runaway agents.

#### 3.4.2 Message Format

Messages follow a simplified version of the Anthropic API message format, adapted for local LLM function-calling via a structured prompt template:

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: list[ContentBlock]   # TextBlock | ToolUseBlock | ToolResultBlock

@dataclass
class TextBlock:
    type: Literal["text"]
    text: str

@dataclass
class ToolUseBlock:
    type: Literal["tool_use"]
    id: str
    name: str
    input: dict

@dataclass
class ToolResultBlock:
    type: Literal["tool_result"]
    tool_use_id: str
    content: str
    is_error: bool = False
```

#### 3.4.3 Tool Calling with Local LLM

Gemma 4 E4B does not natively support OpenAI-style function calling. Tool calls are elicited via **structured prompt injection**:

1. The system prompt includes a `<tools>` XML block listing available tools with JSON schemas.
2. The LLM is instructed to emit tool calls in a structured XML format:
   ```xml
   <tool_use>
   <name>Read</name>
   <input>{"file_path": "src/auth.py"}</input>
   </tool_use>
   ```
3. A regex/XML parser extracts tool calls from the streamed response. Tokens before the first `<tool_use>` tag are streamed as text; the tag itself triggers `tool_start`.
4. After tool execution, a `<tool_result>` block is injected into the next user message.

This mirrors the pattern used in `claude-code`'s `Tool.ts` → `mapToolResultToToolResultBlockParam`.

#### 3.4.4 Tool Registry

Each tool is a Python class implementing:

```python
class Tool(ABC):
    name: str
    description: str
    input_schema: dict          # JSON Schema for the input object

    @abstractmethod
    async def call(self, input: dict, ctx: ToolContext) -> ToolResult:
        ...

    def is_read_only(self, input: dict) -> bool:
        return False

    def requires_permission(self, input: dict, mode: PermissionMode) -> bool:
        return not self.is_read_only(input) and mode != "auto_all"
```

**Built-in tools (MVP):**

| Tool | Read-only | Description |
|---|---|---|
| `Read` | yes | Read file contents with line numbers |
| `Write` | no | Write/overwrite a file |
| `Edit` | no | Exact string replacement in a file |
| `Glob` | yes | Find files matching a glob pattern |
| `Grep` | yes | Search file contents with regex |
| `Bash` | no | Run a shell command (sandboxed by permission mode) |
| `ListDir` | yes | List directory contents |
| `Agent` | — | Spawn a sub-agent with a sub-task |

#### 3.4.5 Permission System

Three modes (configurable in Settings):

| Mode | Behavior |
|---|---|
| `ask` | Prompt user for every non-read-only tool call via `tool_ask` event |
| `auto_read` | Auto-approve read-only tools; ask for writes/bash |
| `auto_all` | Auto-approve everything (use with caution) |

When `ask` mode fires, the Tauri frontend renders an inline approval dialog in the terminal stream. The user types `y`/`n` or clicks a button; the response is sent back as `{"type": "tool_ack", "id": "...", "decision": "allow"|"deny"}`.

#### 3.4.6 Sub-Agent (Agent Tool)

The `Agent` tool spawns a **nested Orchestrator** with:
- Its own message history (clean slate)
- A subset of tools (configurable per-agent)
- A specific task prompt
- Shared working directory and permission mode

Sub-agents run **in-process** (async coroutine), not as separate processes. Their token stream is prefixed with an agent label (e.g., `[explore-agent]`) and forwarded to the parent's output stream. This mirrors `InProcessBackend` in `claude-code/src/utils/swarm/backends/`.

Maximum sub-agent nesting depth: **3**.

#### 3.4.7 Context Management

- **Context window:** Configurable, default 8192 tokens.
- **Compaction:** When the message list exceeds 75% of the context window (measured by a simple character-count heuristic), older tool result messages are summarized and replaced with a `[compacted N tool results]` placeholder. This mirrors `claude-code/src/commands/compact/`.
- **Session storage:** Full conversation history is written to `~/.snowpaw/sessions/<uuid>.jsonl` on each turn for resumability.

---

### 3.5 LLM Backend Abstraction

```python
class LLMBackend(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        system_prompt: str,
        tools_xml: str,
        max_tokens: int,
        temperature: float,
        on_token: Callable[[str], None],   # streaming callback
    ) -> str:  # full generated text
        ...

    @abstractmethod
    def is_loaded(self) -> bool: ...

    @abstractmethod
    async def load(self, model_path: str, on_progress: Callable[[int], None]): ...

    @abstractmethod
    def unload(self): ...
```

#### 3.5.1 Backend Selection (Auto Mode)

At startup, the sidecar probes available memory:

```python
def select_backend() -> type[LLMBackend]:
    vram_gb = get_available_vram_gb()    # via Metal/CUDA query
    ram_gb  = get_available_ram_gb()

    if vram_gb >= 6 or ram_gb >= 12:
        return LlamaCppBackend           # full model in memory
    else:
        return AirLLMBackend             # layer-by-layer, ~4GB RAM
```

Thresholds are conservative to avoid OOM. The user can override in Settings.

#### 3.5.2 AirLLM Backend

- Uses the `airllm` Python package (splits transformer layers across CPU/GPU, loads one at a time).
- Model source: Hugging Face model ID or local directory (Gemma 4 E4B in safetensors format).
- Slower per-token (~2–5 tok/s on CPU) but works on machines with 8GB RAM.
- Streaming: AirLLM generates token-by-token; each token is immediately forwarded via `on_token`.

```python
class AirLLMBackend(LLMBackend):
    def __init__(self):
        self._model = None

    async def load(self, model_path: str, on_progress):
        from airllm import AutoModel
        self._model = AutoModel.from_pretrained(model_path)
        on_progress(100)

    async def generate(self, messages, system_prompt, tools_xml,
                       max_tokens, temperature, on_token):
        prompt = render_prompt(messages, system_prompt, tools_xml)
        for token in self._model.generate(prompt, max_new_tokens=max_tokens,
                                           temperature=temperature,
                                           streaming=True):
            on_token(token)
        return "".join(...)
```

#### 3.5.3 llama.cpp Backend

- Uses `llama-cpp-python` (Python bindings for llama.cpp).
- Model source: GGUF file (Gemma 4 E4B Q4_K_M recommended, ~3.5GB).
- Faster (~10–30 tok/s on CPU, ~50–100 tok/s on Metal/CUDA).
- Streaming: `llama_cpp.Llama.__call__` with `stream=True`.

```python
class LlamaCppBackend(LLMBackend):
    def __init__(self):
        self._llm = None

    async def load(self, model_path: str, on_progress):
        from llama_cpp import Llama
        self._llm = Llama(
            model_path=model_path,
            n_ctx=self._ctx_size,
            n_gpu_layers=-1,        # offload all layers to GPU if available
            verbose=False,
        )
        on_progress(100)

    async def generate(self, messages, system_prompt, tools_xml,
                       max_tokens, temperature, on_token):
        prompt = render_prompt(messages, system_prompt, tools_xml)
        output = self._llm(prompt, max_tokens=max_tokens,
                           temperature=temperature, stream=True)
        full = ""
        for chunk in output:
            tok = chunk["choices"][0]["text"]
            on_token(tok)
            full += tok
        return full
```

#### 3.5.4 Prompt Rendering

Gemma 4 uses the standard Gemma instruction-tuning template:

```
<bos><start_of_turn>user
{system_prompt}

{tools_xml}

{conversation_history}
<end_of_turn>
<start_of_turn>model
```

`tools_xml` is a compact XML block listing tool names, descriptions, and JSON schemas. The system prompt instructs the model to use `<tool_use>` tags to call tools.

---

## 4. Repository Layout

```
snowpaw/
├── design/
│   └── DESIGN.md               ← this document
│
├── src-tauri/                  ← Tauri Rust core
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── binaries/               ← bundled sidecar binaries (gitignored)
│   └── src/
│       ├── main.rs
│       ├── commands.rs         ← Tauri #[command] handlers
│       └── sidecar.rs          ← sidecar spawn + stdio bridge
│
├── src/                        ← Frontend (React + Vite)
│   ├── main.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── Terminal.tsx        ← xterm.js wrapper
│   │   ├── MenuBar.tsx
│   │   └── Settings.tsx
│   ├── hooks/
│   │   ├── useAgent.ts         ← Tauri event listeners, input dispatch
│   │   └── useConfig.ts        ← tauri-plugin-store wrapper
│   └── styles/
│       └── terminal.css
│
├── agent/                      ← Python sidecar source
│   ├── main.py                 ← entry point, NDJSON loop
│   ├── harness/
│   │   ├── orchestrator.py     ← main agent loop
│   │   ├── message.py          ← Message / ContentBlock types
│   │   ├── tool_registry.py    ← Tool ABC + registry
│   │   ├── permissions.py      ← PermissionMode + approval logic
│   │   ├── context_manager.py  ← compaction + token counting
│   │   └── subagent.py         ← Agent tool / nested orchestrator
│   ├── tools/
│   │   ├── read_tool.py
│   │   ├── write_tool.py
│   │   ├── edit_tool.py
│   │   ├── glob_tool.py
│   │   ├── grep_tool.py
│   │   ├── bash_tool.py
│   │   ├── list_dir_tool.py
│   │   └── agent_tool.py
│   ├── backends/
│   │   ├── base.py             ← LLMBackend ABC
│   │   ├── airllm_backend.py
│   │   ├── llamacpp_backend.py
│   │   └── selector.py         ← auto-selection logic
│   ├── prompt/
│   │   ├── system_prompt.py    ← default system prompt
│   │   ├── tools_xml.py        ← tool schema → XML renderer
│   │   └── gemma_template.py   ← Gemma chat template
│   └── requirements.txt
│
├── scripts/
│   ├── build-sidecar.sh        ← PyInstaller build + copy to binaries/
│   └── download-model.sh       ← pulls GGUF from HF
│
├── package.json
└── vite.config.ts
```

---

## 5. Data Flow: End-to-End Example

**User types:** `"add type hints to all functions in src/utils.py"`

```
1. Frontend (Terminal.tsx)
   onData → accumulate → Enter pressed
   invoke("send_input", { text: "add type hints..." })

2. Rust (commands.rs)
   write_to_sidecar_stdin(json!({"type":"input","text":"add type hints..."}))

3. Python (main.py)
   read stdin line → parse JSON → orchestrator.handle_input(text)

4. Orchestrator (orchestrator.py)
   append UserMessage to history
   render system prompt + tools XML
   call backend.generate(..., on_token=emit_token)

5. LLM streams:
   "I'll read the file first.\n<tool_use>\n<name>Read</name>\n<input>..."

6. Parser:
   stream "I'll read the file first.\n" → emit {"type":"token","text":"..."}
   detect <tool_use> → parse → emit {"type":"tool_start","tool":"Read",...}

7. Tool execution:
   ReadTool.call({"file_path":"src/utils.py"}) → read file
   emit {"type":"tool_end","tool":"Read","summary":"Read 87 lines"}
   append ToolResultBlock to messages

8. Orchestrator loops back to LLM:
   LLM streams edit plan + <tool_use> for Edit tool
   (permission check if mode=ask → emit tool_ask → wait for tool_ack)
   EditTool.call(...) → modify file
   emit tool_end

9. LLM streams final response:
   "Done. Added type hints to 12 functions in src/utils.py."
   emit {"type":"token","text":"Done..."}
   emit {"type":"status","phase":"idle"}

10. Frontend:
    xterm renders all tokens in real time
    Shows tool use blocks with collapsible details
    Prompt > reappears
```

---

## 6. System Prompt

The default system prompt (in `agent/prompt/system_prompt.py`) establishes the agent's identity and operating rules:

```
You are SnowPaw, a local coding assistant running on this machine.
You have access to the user's filesystem and shell. You help with
programming tasks: reading code, making edits, running tests, and
explaining concepts.

Rules:
- Always read a file before editing it.
- Prefer targeted edits over full rewrites.
- Do not run destructive shell commands without explicit user instruction.
- When unsure, ask rather than assume.
- Work in the directory: {working_directory}

Use the provided tools to accomplish tasks. Emit tool calls using
<tool_use> XML tags as described in the tools section.
```

---

## 7. Permission Model

Mirrors `claude-code`'s `ToolPermissionContext` but simplified to three levels:

```python
class PermissionMode(Enum):
    ASK       = "ask"        # prompt for every write/bash
    AUTO_READ = "auto_read"  # auto-allow reads, ask for writes
    AUTO_ALL  = "auto_all"   # allow everything silently
```

The orchestrator calls `permissions.check(tool, input, mode)` before executing any tool. In `ASK` mode, it suspends the coroutine and emits a `tool_ask` event. The Rust layer holds the response channel; the frontend renders the approval UI and sends back `tool_ack`. The coroutine resumes.

---

## 8. Model Selection & Bundling

### Recommended model: Gemma 4 E4B (MoE)

| Backend | Format | Size | RAM needed | Speed (M3 Pro) |
|---|---|---|---|---|
| llama.cpp | GGUF Q4_K_M | ~3.5 GB | ~5 GB | ~25 tok/s |
| AirLLM | HF safetensors | ~8 GB on disk | ~4 GB peak | ~3 tok/s |

The app ships **without** the model weights (too large). On first launch, a setup wizard prompts the user to either:
1. Download the GGUF automatically (via `scripts/download-model.sh` invoked from the frontend), or
2. Point to an existing local model file.

Model path is stored in `snowpaw.conf.json`.

---

## 9. Build & Distribution

### Development

```bash
# Install Python deps
cd agent && pip install -r requirements.txt

# Build sidecar
./scripts/build-sidecar.sh   # outputs agent/dist/snowpaw-agent

# Copy to Tauri binaries
cp agent/dist/snowpaw-agent \
   src-tauri/binaries/snowpaw-agent-aarch64-apple-darwin

# Run dev
npm run tauri dev
```

### Production

```bash
npm run tauri build
# → src-tauri/target/release/bundle/dmg/SnowPaw_*.dmg  (macOS)
# → src-tauri/target/release/bundle/nsis/SnowPaw_*.exe (Windows)
# → src-tauri/target/release/bundle/deb/snowpaw_*.deb  (Linux)
```

The sidecar binary is embedded in the app bundle by Tauri's `externalBin` mechanism. The model weights are downloaded post-install.

---

## 10. Key Design Decisions & Trade-offs

| Decision | Rationale |
|---|---|
| **Sidecar over Tauri plugin** | Python has the best ecosystem for AI/ML (AirLLM, llama-cpp-python). A Rust plugin would require FFI bindings. Sidecar keeps the boundary clean. |
| **NDJSON over WebSocket/IPC** | Simplest possible protocol. Tauri's sidecar stdin/stdout is a reliable, buffered channel. No extra server port needed. |
| **xterm.js over custom renderer** | Gives authentic terminal feel with ANSI support for free. Matches the target UX (looks like Claude Code). |
| **XML tool-call format** | Gemma 4 is instruction-tuned but not function-calling tuned. XML is more reliably parseable from free-form LLM output than JSON embedded in prose. |
| **In-process sub-agents** | Avoids the complexity of spawning child processes for sub-agents. The Python asyncio event loop handles concurrency. Simpler permission propagation. |
| **AirLLM fallback** | Enables the app to run on machines with only 8GB RAM (e.g., base MacBook Air M1). Without this, the app would be unusable on the most common developer laptops. |
| **No streaming to disk during generation** | Tokens are streamed directly to the Tauri event bus. Session JSONL is written per-turn (not per-token) to avoid excessive I/O. |

---

## 11. MVP Scope vs. Future Work

### MVP (v0.1)

- [x] Tauri shell with sidecar lifecycle
- [x] xterm.js terminal UI with streaming token display
- [x] Menu bar: open folder, new session, model status
- [x] Settings page (backend, model path, permissions, temperature)
- [x] Agent harness: orchestrator loop, tool calling, permission system
- [x] Tools: Read, Write, Edit, Glob, Grep, Bash, ListDir
- [x] Sub-agent (Agent tool, depth ≤ 3)
- [x] llama.cpp backend (GGUF)
- [x] AirLLM backend (safetensors)
- [x] Auto backend selection
- [x] Context compaction at 75% fill
- [x] Session persistence (JSONL)

### Future Work

- [ ] **Session resume** — reload a previous JSONL session
- [ ] **Multi-pane** — split terminal for agent + sub-agent views (like tmux swarm in claude-code)
- [ ] **MCP server support** — connect to local MCP servers for extended tools
- [ ] **Voice input** — whisper.cpp sidecar for speech-to-text
- [ ] **Diff viewer** — inline side-by-side diff for file edits (like claude-code's Edit tool rendering)
- [ ] **Plan mode** — two-phase: plan → user approval → execute
- [ ] **Model fine-tuning UI** — LoRA fine-tune on local codebase
- [ ] **Windows / Linux** — initial target is macOS; cross-platform after MVP

---

## 12. Security Considerations

- **No network access by default.** The sidecar has no outbound network calls. The LLM runs fully offline.
- **Bash sandboxing.** In `ASK` and `AUTO_READ` modes, Bash commands require explicit user approval. The system prompt instructs the model not to run destructive commands.
- **Path traversal.** The `Read`/`Write`/`Edit` tools validate that the resolved path is within the configured working directory (or its parents, for multi-repo setups).
- **Sidecar isolation.** The Python sidecar runs as the same user as the app (no privilege escalation). There is no network socket — all communication is via stdin/stdout.
- **Model integrity.** GGUF/safetensors files are checksummed against known-good hashes after download.
