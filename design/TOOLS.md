# CyberPaw — Tool Analysis Report

> Comparing claude-code's tool surface against CyberPaw's implementation.
> Generated: 2026-04-14

---

## 1. Tools Available in `./claude-code`

Claude Code (TypeScript) exposes **40+ tools** organised into functional groups.

### 1.1 File & Code Operations

| Tool | Description |
|---|---|
| `Read` | Read files with line numbers, offset, and limit; supports PDFs, images, notebooks |
| `FileEdit` | Targeted exact-string replacement in a file |
| `MultiEdit` | Apply a list of `{old_string, new_string}` edits to a single file atomically |
| `FileWrite` | Create or overwrite a file |
| `Glob` | Find files matching a glob pattern, sorted by mtime |
| `Grep` | Regex search across file contents with optional file-glob filter |
| `ListDir` | List directory contents with sizes and types |
| `NotebookEdit` | Edit Jupyter notebook cells (replace / insert / delete) |

### 1.2 Execution & Terminal

| Tool | Description |
|---|---|
| `Bash` | Execute shell commands with timeout and output truncation |
| `REPL` | Interactive code execution environment (persistent state) |
| `SleepTool` | Pause execution for a fixed duration |

### 1.3 Web & Network

| Tool | Description |
|---|---|
| `WebSearch` | Search the web; results include mandatory Sources section |
| `WebFetch` | Fetch a URL, convert HTML → markdown, process with a fast model |

### 1.4 Task & Project Management

| Tool | Description |
|---|---|
| `TaskCreate` | Create a named task with description |
| `TaskGet` | Retrieve full task details by ID |
| `TaskList` | List all tasks with status and blockers |
| `TaskUpdate` | Update status, owner, subject, dependencies |
| `TaskStop` | Cancel a running background task |
| `TaskOutput` | Get output from a background task |
| `TodoWrite` | Write a persistent to-do list to disk |

### 1.5 Multi-Agent & Scheduling

| Tool | Description |
|---|---|
| `Agent` | Spawn a sub-agent for parallelisable work (depth-limited) |
| `RemoteTrigger` | Call remote-triggered APIs / webhooks |
| `CronCreate` | Schedule a recurring or one-shot cron job |
| `CronDelete` | Cancel a scheduled cron job |
| `CronList` | List all active cron jobs |

### 1.6 Planning & Workflow

| Tool | Description |
|---|---|
| `EnterPlanMode` | Switch to plan mode for design-before-execute workflow |
| `ExitPlanMode` | Finalise plan and request user approval |
| `Skill` | Invoke a named skill plugin |

### 1.7 Git Isolation

| Tool | Description |
|---|---|
| `EnterWorktree` | Create / enter an isolated git worktree |
| `ExitWorktree` | Leave a worktree (keep or remove) |

### 1.8 MCP Integration

| Tool | Description |
|---|---|
| `MCPTool` | Call a Model Context Protocol server |
| `ListMcpResources` | Browse MCP resources |
| `ReadMcpResource` | Read a specific MCP resource |
| `McpAuth` | Handle MCP authentication |

### 1.9 UI & Interaction

| Tool | Description |
|---|---|
| `AskUserQuestion` | Present a structured question to the user |
| `SendMessage` | Send a system message |
| `BriefTool` | Generate a short briefing |

### 1.10 Developer Tooling

| Tool | Description |
|---|---|
| `LSPTool` | Language Server Protocol integration (go-to-def, diagnostics) |
| `NotebookEdit` | Edit Jupyter notebook cells |
| `ToolSearch` | Find and inspect available tools |
| `ConfigTool` | Read / write configuration |

---

## 2. Tools Implemented in `./cyberpaw` (as of 2026-04-14)

### 2.1 File & Code Operations
| Tool | Read-only | Status |
|---|---|---|
| `Read` | yes | ✅ implemented |
| `Write` | no | ✅ implemented |
| `Edit` | no | ✅ implemented |
| `MultiEdit` | no | ✅ implemented |
| `Glob` | yes | ✅ implemented |
| `Grep` | yes | ✅ implemented |
| `ListDir` | yes | ✅ implemented |
| `Move` | no | ✅ implemented |
| `DeleteFile` | no | ✅ implemented |

### 2.2 Execution & Terminal
| Tool | Read-only | Status |
|---|---|---|
| `Bash` | no | ✅ implemented |
| `REPL` | no | ✅ implemented |
| `Sleep` | yes | ✅ implemented |

### 2.3 Web & Network
| Tool | Read-only | Status |
|---|---|---|
| `WebFetch` | no | ✅ implemented (opt-in, off by default) |
| `WebSearch` | no | ✅ implemented (opt-in, off by default) |

### 2.4 Task & Project Management
| Tool | Read-only | Status |
|---|---|---|
| `TodoWrite` | no | ✅ implemented |
| `TaskCreate` | no | ✅ implemented |
| `TaskGet` | yes | ✅ implemented |
| `TaskList` | yes | ✅ implemented |
| `TaskUpdate` | no | ✅ implemented |
| `TaskStop` | no | ✅ implemented |
| `TaskOutput` | yes | ✅ implemented (stub) |

### 2.5 Multi-Agent
| Tool | Read-only | Status |
|---|---|---|
| `Agent` | — | ✅ implemented |

---

## 3. Gap Analysis — File Operations

The file-ops category in claude-code that CyberPaw was missing:

| claude-code tool | CyberPaw equivalent | Gap |
|---|---|---|
| `Read` | `Read` | covered |
| `FileWrite` | `Write` | covered |
| `FileEdit` | `Edit` | covered |
| `MultiEdit` | — | **gap → added `MultiEdit`** |
| `Glob` | `Glob` | covered |
| `Grep` | `Grep` | covered |
| `ListDir` | `ListDir` | covered |
| *(implicit)* rename/move | — | **gap → added `Move`** |
| *(implicit)* delete file | — | **gap → added `DeleteFile`** |
| `NotebookEdit` | — | out of scope (no Jupyter in MVP) |

---

## 4. Recommended Next Tools (Priority Order)

These are tools beyond file ops that would most benefit CyberPaw given its offline,
small-model constraints:

### Tier 1 — High value, low complexity

| Tool | Rationale | Status |
|---|---|---|
| `TodoWrite` | Helps the model track multi-step work across turns; pure filesystem op | ✅ done |
| `Sleep` | Trivial to implement; needed for polling loops and retry back-off | ✅ done |
| `REPL` | Persistent Python interpreter; useful for data analysis and scripting | ✅ done |

### Tier 2 — High value, moderate complexity

| Tool | Rationale | Status |
|---|---|---|
| `TaskCreate` / `TaskList` / `TaskUpdate` | In-memory task tracking; helps the model self-organise on long refactors | ✅ done |
| `WebFetch` / `WebSearch` | Network access (opt-in, off by default) | ✅ done |
| `EnterPlanMode` / `ExitPlanMode` | Two-phase plan→approve→execute; especially valuable with a small model | not started |
| `AskUserQuestion` | Structured clarification prompts; improves UX for ambiguous tasks | not started |

### Tier 3 — Stretch goals

| Tool | Rationale | Status |
|---|---|---|
| `NotebookEdit` | Useful for data science workflows; pure local file op | not started |
| `LSPTool` | Language server integration for diagnostics and go-to-definition | not started |

### Skip (incompatible with offline-first design)

`MCP*`, `RemoteTrigger`, `CronCreate`, `EnterWorktree` / `ExitWorktree`
(require git, or external services).

---

## 5. Architecture Notes

### Tool calling mechanism

CyberPaw uses **XML-structured tool calls** injected into the prompt because Gemma 4
is not function-calling tuned:

```xml
<tool_use>
<name>Read</name>
<input>{"file_path": "src/auth.py"}</input>
</tool_use>
```

Each tool is a Python class inheriting from `Tool` (ABC) in
`agent/harness/tool_registry.py`, implementing:

- `name`, `description`, `input_schema` — class attributes
- `call(input, ctx) -> ToolResult` — async execution
- `is_read_only(input) -> bool` — permission gating

### Permission model

| Mode | Behaviour |
|---|---|
| `ASK` | Prompt user for every non-read-only call via `tool_ask` event |
| `AUTO_READ` | Auto-approve read-only tools; ask for writes/bash |
| `AUTO_ALL` | Auto-approve everything |

### Key differences from claude-code

| Aspect | claude-code | CyberPaw |
|---|---|---|
| Language | TypeScript | Python |
| LLM | Claude API (remote) | Gemma 4 E2B/E4B (local) |
| Tool calling | Native function-calling API | Structured XML injection |
| Tool count | 40+ | 29 (as of 2026-04-15) |
| Network | Required | None (offline-first) |
| Sub-agents | Process-isolated | In-process async coroutines |
