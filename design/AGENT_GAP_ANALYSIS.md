# CyberPaw Agent Layer — Gap Analysis vs. Claude Code

> A systematic comparison of CyberPaw's Python agent harness against the Claude Code reference
> implementation. Each gap is rated by **impact**, **effort**, and **local-model fit** — the last
> dimension is the most important: several Claude Code features are cloud-model luxuries that would
> hurt a small local model more than they help.

---

## Rating Key

| Dimension | Scale |
|-----------|-------|
| **Impact** | High / Medium / Low — how much better the agent behaves if this is added |
| **Effort** | S / M / L / XL — S = hours, M = 1-3 days, L = 1-2 weeks, XL = weeks+ |
| **Local-model fit** | ✅ Essential / ⚠️ Conditional / ❌ Counterproductive |

---

## Gap 1 — Inaccurate Token Counting

### Current state
`context_manager.py` estimates tokens with `total_characters / 4` (line 28). This is a
model-agnostic heuristic. For Gemma 4 (a SentencePiece-based tokenizer), the actual token count
can diverge by 30–50% depending on code density, Unicode content, and special tokens. The
compaction threshold fires at 75% of `context_size`, so a 40% under-count means the model
silently hits `max_context` mid-generation, producing truncated or repeated output with no
diagnostic.

### Claude Code approach
`tokenCountWithEstimation()` in `autoCompact.ts` calls the Anthropic token-counting API
(`POST /v1/messages/count_tokens`) before deciding to compact. Falls back to a character
heuristic only when the API is unavailable. Cost is tracked per call.

### Impact
**High.** With an 8 192-token window the margin for error is small. Overestimating means
unnecessary compaction (losing context that was still useful). Underestimating means the model
hits the hard limit and the generation is silently cut.

### Effort
**S.** `llama-cpp-python` exposes the model's tokenizer:

```python
# agent/backends/llamacpp_backend.py
def count_tokens(self, text: str) -> int:
    if self._llm is None:
        return len(text) // 4
    tokens = self._llm.tokenize(text.encode())
    return len(tokens)
```

`context_manager.py` calls `backend.count_tokens()` instead of the character heuristic.
`LLMBackend.count_tokens()` gets a default fallback in `base.py`.

### Local-model fit
✅ **Essential.** Small context windows make every token count. The fix is cheap and the payoff
is immediate.

---

## Gap 2 — Flat Compaction (No Tiered Summarisation)

### Current state
When `should_compact()` fires, `compact()` in `context_manager.py` (lines 39–75) applies a
single strategy to all messages older than the last 6 turns: any `ToolResultBlock` whose content
exceeds 200 characters is replaced with the first 120 characters plus `" … [compacted]"`. The
full content is discarded. There is no summarisation step and no distinction between a 300-byte
grep result and a 40 000-byte file read.

### Claude Code approach
Three layers:
1. **Snipping** — large tool results are persisted to disk before the compaction call; the model
   receives a path-reference plus a short preview. The `maxResultSizeChars` per-tool limit governs
   this (set to `Infinity` for Read to prevent loops).
2. **Summarisation** — a second LLM call produces a prose summary of the conversation so far.
   The summary replaces the raw history, preserving intent without raw tokens.
3. **Budget tracking across compactions** — `taskBudgetRemaining` accumulates pre-compact context
   so the model knows how much history it has implicitly consumed.

### Impact
**High.** With a small model and an 8 192-token window, compaction fires frequently. Silently
discarding tool results causes the model to re-read files it already processed, inflating turn
counts and degrading task coherence.

### Effort
**M.** Tiered approach for CyberPaw:

**Tier 0 (keep):** last `KEEP_RECENT_TURNS * 2` messages — unchanged.

**Tier 1 (summarise tool results):** For `ToolResultBlock` content between 200 and 4 000 chars,
keep the first 100 and last 100 characters plus a middle marker
`\n… [N chars, compacted] …\n`. This is already partially done; extend it to all sizes not just
>200 chars.

**Tier 2 (persist large outputs to disk):** For any tool result exceeding `MAX_TOOL_RESULT_CHARS`
(currently 4 000), write the full content to `.cyberpaw/session/{session_id}/{tool_id}.txt` and
replace the block content with:
```
[Full output saved to .cyberpaw/session/{session_id}/{tool_id}.txt]
First 200 chars: {preview}
```
The model can re-read the file with the Read tool if needed.

**Tier 3 (LLM summarisation — conditional):** A second LLM call to summarise old turns is
expensive on local hardware. Defer this to Phase 2 or make it opt-in.

### Local-model fit
✅ **Essential (Tiers 0–2).** Disk persistence is free; it trades a few KB of disk space for
context headroom. Tier 3 (LLM summarisation) is ⚠️ **Conditional** — it costs a full inference
pass and may not be worth it for a 4B model.

---

## Gap 3 — No Staleness Guard on File Edits

### Current state
`edit_tool.py` performs an exact string match and replaces the first occurrence. There is no
check of whether the file was modified between the last `Read` call and the `Edit` call. If a
linter, formatter, or another agent turn rewrites the file between the two calls, the edit
silently applies to stale content, producing a corrupted result.

### Claude Code approach
`FileEditTool.ts` (lines 275–311):
1. Reads the `readFileState` timestamp stored when the file was last read.
2. Fetches current `mtime` via `getFileModificationTime()`.
3. If `mtime > readTimestamp`, does a byte-for-byte content comparison (handles filesystem
   timestamp quirks on Windows).
4. If content changed, rejects the edit with `FILE_UNEXPECTEDLY_MODIFIED_ERROR` and asks the
   model to re-read.
5. The staleness check is inside a critical section — no async gap between check and write.

### Impact
**Medium.** Rare in solo sessions but frequent when the user has an auto-formatter running (e.g.,
`ruff --fix` on save) or when the agent uses Bash to run a formatter before editing. Silent
corruption is worse than a visible error.

### Effort
**S.** In `edit_tool.py`:

```python
# Store read timestamp in a module-level dict keyed by (session_id, abs_path)
_read_timestamps: dict[tuple[str, str], float] = {}

# In ReadTool.call():
_read_timestamps[(ctx.session_id, abs_path)] = os.path.getmtime(abs_path)

# In EditTool.call(), before applying the edit:
last_read = _read_timestamps.get((ctx.session_id, abs_path))
if last_read is not None:
    current_mtime = os.path.getmtime(abs_path)
    if current_mtime > last_read + 0.01:   # 10ms tolerance
        return ToolResult.error(
            f"File was modified since last read (mtime changed). "
            f"Re-read {file_path} before editing."
        )
```

Clear the entry on successful write/edit.

### Local-model fit
✅ **Essential.** Small models are more likely to emit a stale `old_string` after a long tool
chain. Failing loudly is far better than silent corruption.

---

## Gap 4 — No Quote Normalisation in Edit Matching

### Current state
`edit_tool.py` uses `content.replace(old_string, new_string, 1)` with no preprocessing. If the
model outputs a curly/smart quote (`"`, `"`, `'`, `'`) instead of a straight quote (`"`, `'`),
the match fails even though the intent is clear.

### Claude Code approach
`utils.ts` in `FileEditTool` (lines 73–93):
1. Tries exact match first.
2. Normalises curly quotes → straight quotes in both `fileContent` and `searchString`.
3. Searches the normalised file for the normalised pattern.
4. Returns the substring from the **original** file at the matched position, preserving the
   file's original typography.
5. Applies the same normalisation to `new_string` to preserve quote style in the replacement.

### Impact
**Medium.** Local models trained on diverse text often emit curly quotes in code contexts. Every
failed edit costs a full LLM turn to retry.

### Effort
**S.**

```python
# agent/tools/edit_tool.py — add before the exact match attempt

_CURLY_QUOTE_MAP = str.maketrans('""''', '"\'"\'')

def _normalise_quotes(s: str) -> str:
    return s.translate(_CURLY_QUOTE_MAP)

def _find_with_normalisation(content: str, old: str) -> tuple[int, int] | None:
    norm_content = _normalise_quotes(content)
    norm_old = _normalise_quotes(old)
    idx = norm_content.find(norm_old)
    if idx == -1:
        return None
    return idx, idx + len(norm_old)
```

In `call()`, try exact match first; fall back to `_find_with_normalisation` and splice from the
original `content`.

### Local-model fit
✅ **Essential.** Local models emit curly quotes more often than Claude. The fix is ten lines and
has no downside.

---

## Gap 5 — No Fuzzy Path Recovery on ENOENT

### Current state
If the model passes a wrong path to Read, Edit, or Glob, the tool returns a plain
`FileNotFoundError` message. The model must guess a correction and retry, consuming a full turn.

### Claude Code approach
On `ENOENT`, the tool performs a quick `glob` for similarly-named files in the parent directory
and appends the suggestions to the error message:
```
File not found: src/components/Terminl.tsx
Did you mean one of:
  src/components/Terminal.tsx
  src/components/TerminalWrapper.tsx
```

### Impact
**Medium.** Typos in file paths are common with small models. Each miss costs a turn, and with
a 40-turn cap and small context, wasted turns are expensive.

### Effort
**S.** Add a helper to `agent/tools/` or `agent/harness/`:

```python
import difflib, glob as _glob, os

def suggest_paths(missing: str, working_dir: str, n: int = 3) -> list[str]:
    parent = os.path.dirname(os.path.join(working_dir, missing))
    if not os.path.isdir(parent):
        parent = working_dir
    candidates = _glob.glob(os.path.join(parent, "**", "*"), recursive=True)
    rel = [os.path.relpath(c, working_dir) for c in candidates if os.path.isfile(c)]
    return difflib.get_close_matches(missing, rel, n=n, cutoff=0.5)
```

Call in `ReadTool`, `EditTool`, `WriteTool` on `FileNotFoundError` and append suggestions to the
error string.

### Local-model fit
✅ **Essential.** Small models hallucinate paths more frequently. One-time glob cost is negligible.

---

## Gap 6 — Static System Prompt (No Project Context Injection)

### Current state
`system_prompt.py` injects today's date, platform, and `working_directory`. It does not include
any information about the project structure, active files, or recent git activity. The model must
discover the project layout entirely through tool calls.

### Claude Code approach
`context.ts` (lines 36–149) runs five `git` commands in parallel on startup
(`branch`, `default-branch`, `status`, `log`, `user.name`), truncates status to 2 000 chars, and
injects the result into the system prompt. A separate `CLAUDE.md` injection step adds
project-specific instructions.

### Impact
**High.** Without a project map, the model's first 3–5 turns are typically spent exploring the
directory tree. With an 8 192-token window and a 40-turn cap, that exploration consumes a
disproportionate share of both.

### Effort
**M.** Two-phase injection:

**Phase 1 — git context (cheap, run once):**
```python
# agent/prompt/system_prompt.py
import subprocess, shutil

def _git_context(cwd: str) -> str:
    if not shutil.which("git"):
        return ""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, text=True, timeout=3
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=cwd, text=True, timeout=3
        ).strip()[:1000]
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            cwd=cwd, text=True, timeout=3
        ).strip()
        return f"Git branch: {branch}\nRecent commits:\n{log}\nWorking tree:\n{status}"
    except Exception:
        return ""
```

**Phase 2 — CLAUDE.md / project instructions (read once on `cd`):**
Look for `CLAUDE.md` or `AGENTS.md` in `working_directory` and its parents (up to 3 levels).
Inject the first found file's content (capped at 2 000 chars) into the system prompt.

Both are regenerated when `set_working_directory()` is called.

### Local-model fit
✅ **Essential.** Reducing discovery turns is critical when context is scarce. Git context is
~200 tokens — a worthwhile trade.

---

## Gap 7 — No `<thought>` / Reasoning Block Before Tool Use

### Current state
The orchestrator streams the model's raw output and parses `<tool_use>` blocks from it. There is
no explicit structure that encourages the model to reason before committing to a tool call. Small
models frequently emit tool calls that are semantically correct but tactically wrong (e.g.,
editing the wrong file, running a destructive command without checking first).

### Claude Code approach
Claude models natively support extended thinking blocks. The `QueryEngine` passes
`thinking: {type: "enabled", budget_tokens: N}` when the feature is on. The thinking block is
stripped from the message history before the next turn to avoid re-consuming tokens.

### Impact
**Medium.** Forcing a reasoning step before tool use reduces wrong-file edits and unnecessary
destructive commands. The gain is larger for smaller models that have weaker implicit planning.

### Effort
**M.** Gemma 4 supports `<thought>` blocks in its instruction-tuning format. Add to the system
prompt:

```
Before every tool call, write a brief <thought> block:
  <thought>I need to edit src/App.tsx line 42 to fix the null check.</thought>
  <tool_use>...
```

In the orchestrator's streaming filter (`_stream_llm`), suppress `<thought>...</thought>` blocks
from the token stream sent to the UI (same as `<tool_use>` suppression today). Strip them from
the assistant message stored in history to avoid re-consuming tokens next turn.

### Local-model fit
⚠️ **Conditional.** A `<thought>` block costs 50–150 tokens per tool call. On an 8 192-token
window with many tool calls, this adds up. Enable by default but make it a config flag
(`enable_thoughts: bool`, default `True`). Disable automatically if `context_size < 4096`.

---

## Gap 8 — No Prompt-Prefix KV Cache Management

### Current state
`llamacpp_backend.py` calls `self._llm(prompt, ...)` on every turn, passing the full rendered
conversation as a single string. `llama.cpp` internally caches KV states for the longest common
prefix between consecutive calls, but this is only effective if the prefix is byte-identical.
Because `gemma_template.py` re-renders the entire history on every turn (including timestamps or
dynamic fields), the cache may be invalidated on every call, causing full re-evaluation of the
system prompt and tool definitions on each turn.

### Claude Code approach
Uses Anthropic's prompt caching API (`cache_control: {type: "ephemeral"}`) on the system prompt
and the first few stable turns. Cache creation costs 25% more; cache hits cost 10% of the base
price. The cache TTL is 5 minutes.

### Impact
**High.** The system prompt + tools XML is ~1 500–2 000 tokens. Re-evaluating it on every turn
wastes ~30% of the per-turn compute budget. For a 4B model running on CPU, this is the
difference between a 3-second and a 4-second TTFT per turn.

### Effort
**M.** Two changes:

1. **Stabilise the prompt prefix.** Move all dynamic content (date, git context) out of the
   system prompt and into the first `user` message. The system prompt becomes static for the
   lifetime of the session. `llama.cpp` will then cache it after the first call.

2. **Explicit prefix caching in `llamacpp_backend.py`:**
```python
# After loading the model, pre-fill the system prompt into the KV cache:
async def prime_cache(self, system_prefix: str) -> None:
    """Warm the KV cache with the stable system prompt prefix."""
    tokens = self._llm.tokenize(system_prefix.encode())
    self._llm.eval(tokens)   # fills KV cache, discards logits
    self._cached_prefix_len = len(tokens)
```
Pass `n_past=self._cached_prefix_len` on subsequent calls to skip re-evaluation.

### Local-model fit
✅ **Essential.** This is the single highest-leverage performance optimisation available. The
system prompt and tools XML are static; caching them is free after the first turn.

---

## Gap 9 — XML Tool-Call Format is Fragile for Small Models

### Current state
Tool calls use a custom XML schema:
```xml
<tool_use>
  <name>read_file</name>
  <input>{"file_path": "src/App.tsx"}</input>
</tool_use>
```
Parsed by regex in `orchestrator.py` (lines 50–52). The regex handles missing closing tags for
streaming, but small models frequently:
- Omit the `<input>` wrapper and emit raw JSON
- Mix XML and JSON (`<tool_use>{"name": "read_file", ...}</tool_use>`)
- Emit partial tags that the regex cannot recover from

### Claude Code approach
Uses the Anthropic API's native structured tool-call format. The API guarantees well-formed
tool-call JSON; the client never needs to parse XML.

### Impact
**High.** Parse failures silently fall through as plain text, causing the model to believe the
tool ran when it did not. The next turn then produces nonsensical follow-up.

### Effort
**L.** Two options:

**Option A — Harden the regex parser (quick fix):**
Add fallback patterns:
```python
# Try 1: standard <tool_use>...</tool_use>
# Try 2: bare JSON object with "name" key on its own line
# Try 3: ```json fenced block containing tool call
```
Emit a clear error message when none match, so the model can retry.

**Option B — Migrate to JSON tool calls (correct fix):**
Change the system prompt to request:
```json
{"tool": "read_file", "input": {"file_path": "src/App.tsx"}}
```
Emit a JSON schema of all tools in the system prompt instead of XML. Parse with
`json.loads()` on any line that starts with `{`. This is more robust for small models that
have seen JSON in training far more often than custom XML schemas.

Option B is the right long-term direction; Option A is the pragmatic short-term fix.

### Local-model fit
✅ **Essential.** Small models are worse at adhering to novel XML schemas. JSON is universally
in their training distribution.

---

## Gap 10 — No Secret / Credential Scanning

### Current state
`write_tool.py` and `edit_tool.py` write content to disk with no inspection. `bash_tool.py`
blocks a small set of destructive patterns (`rm -rf /`, `mkfs`, `dd if=`, fork bomb) but has no
awareness of credential exposure.

### Claude Code approach
A regex-based scanner runs on tool inputs before execution. Patterns include:
- AWS key format (`AKIA[0-9A-Z]{16}`)
- Generic `*_API_KEY`, `*_SECRET`, `*_TOKEN` variable assignments
- Private key PEM headers
- `.env` file writes containing secrets

### Impact
**Low** in solo local use. The model is running offline and the user controls the machine. Worth
adding as a warning (not a hard block) to prevent accidental writes.

### Effort
**S.** Add `agent/harness/secret_scanner.py`:

```python
import re

_PATTERNS = [
    re.compile(r'AKIA[0-9A-Z]{16}'),                         # AWS key
    re.compile(r'(?i)(api_key|secret|token)\s*=\s*["\'][^"\']{8,}'),
    re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'),
]

def scan(text: str) -> list[str]:
    return [p.pattern for p in _PATTERNS if p.search(text)]
```

Call in `WriteTool` and `EditTool`; if matches found, prepend a `⚠ Possible credential in
output` warning to the `ToolResult.output` (do not block — the user may be intentionally
writing a test fixture).

### Local-model fit
⚠️ **Conditional.** Useful as a warning; not worth blocking on in an offline-only tool.

---

## Gap 11 — No Budget-Aware Turn Cap (Soft + Hard Limits)

### Current state
`orchestrator.py` enforces `MAX_TURNS = 40` (line 45) as a hard cap with no intermediate
warnings. There is no per-session budget tracking, no cost display, and no way to set a lower
cap per task.

### Claude Code approach
`QueryEngine.ts` accepts `maxTurns` and `maxBudgetUsd` per query. The loop checks both after
every tool call. A `budgetTracker` accumulates token counts across compaction boundaries. The UI
shows a running cost display.

### Impact
**Low** for offline use (no API cost). The turn cap matters because small models on slow hardware
can run for minutes on a 40-turn loop. A visible turn counter and a configurable soft warning
would improve UX.

### Effort
**S.** In `orchestrator.py`, emit a `{"type": "status", "turn": N, "max_turns": MAX_TURNS}`
event on each iteration. In `MenuBar.tsx`, display the turn counter when the agent is active.
Add `max_turns` to the config schema so users can lower it for quick tasks.

### Local-model fit
✅ **Essential** as a UX improvement. The hard cap is already there; surfacing it costs nothing.

---

## Gap 12 — Sub-Agent Architecture Has No Specialisation

### Current state
`subagent.py` spawns a fresh `Orchestrator` with a copy of all tools except `Agent`. The
sub-agent gets the same system prompt and tool set as the parent. There is no way to create a
read-only sub-agent, a web-research sub-agent, or a code-review sub-agent.

### Claude Code approach
`coordinatorMode.ts` restricts worker tool sets by mode. Simple workers get only Bash, Read,
Edit. Coordinator workers get a broader set minus internal routing tools. Workers can read/write
a shared scratchpad directory for cross-agent knowledge.

### Impact
**Medium.** Specialised sub-agents are safer (read-only sub-agents cannot corrupt files) and
more token-efficient (smaller tool XML = more context for the task). The scratchpad pattern is
especially useful for multi-file refactors.

### Effort
**M.** Add a `tool_filter: list[str] | None` parameter to `run_subagent()`. Pass it from
`AgentTool` via a new `mode` input field (`"read_only"` | `"full"` | `"web_only"`). Map modes to
tool name allowlists in `subagent.py`. A shared scratchpad can be a session-scoped temp
directory injected into `ToolContext`.

### Local-model fit
⚠️ **Conditional.** With a 4B model, deep sub-agent chains are slow. Specialisation is most
useful when the user explicitly invokes multi-agent workflows. Do not add complexity for
single-turn tasks.

---

## Gap 13 — No Persistent Session History / Resume

### Current state
Message history lives in `orchestrator.messages` (in-memory). A `reset` command clears it. There
is no export, no resume-from-file, and no way to continue a session after the app restarts.

### Claude Code approach
`QueryEngine.ts` persists every user message to a transcript file **before** entering the query
loop (lines 450–463). On startup, `sessionHistory.ts` paginates through stored events to
reconstruct the conversation. The `--resume` CLI flag picks up where the last session left off.

### Impact
**Medium.** For long coding sessions (30+ minutes), losing context on app restart is painful.

### Effort
**L.** On each user input and assistant response, append a JSON line to
`.cyberpaw/sessions/{session_id}.jsonl`. On startup, offer a "Resume last session" option that
replays the JSONL into `orchestrator.messages`. The tricky part is replaying tool results without
re-executing tools.

### Local-model fit
⚠️ **Conditional.** Useful but not urgent. The 8 192-token window means most sessions compact
before they accumulate enough history to be worth resuming. Prioritise after Gaps 1–8.

---

## Gap 14 — No Background Memory Consolidation (Dream System)

### Current state
There is no equivalent to Claude Code's auto-dream system. Long-term context (project
conventions, past decisions, recurring patterns) must be re-discovered on every session.

### Claude Code approach
`autoDream.ts` runs a forked sub-agent every 24 hours (or after 5 sessions), reads `MEMORY.md`,
gathers signals from daily logs, consolidates durable facts, and prunes stale entries. Triple-
gated: time, session count, and a file lock to prevent concurrent dreams.

### Impact
**Low** in the short term. Meaningful only after many sessions. The benefit compounds over time.

### Effort
**XL.** Requires session logging (Gap 13), a reliable sub-agent (Gap 12), and a small-model-
capable summarisation prompt. The triple-gating logic is non-trivial.

### Local-model fit
⚠️ **Conditional.** A 4B model summarising its own history may produce low-quality memories.
The value depends heavily on model quality. Consider a simpler alternative: after each session,
ask the model to append 2–3 bullet points to `MEMORY.md` describing what it learned. This is
cheaper than a full dream pass and more reliable at small model sizes.

---

## Prioritised Implementation Roadmap

### Phase 1 — Correctness & Reliability (1–2 weeks)

| # | Gap | Effort | Why first |
|---|-----|--------|-----------|
| 1 | Exact token counting | S | Prevents silent context overflow |
| 3 | Staleness guard on edits | S | Prevents silent file corruption |
| 4 | Quote normalisation | S | Reduces edit retry rate |
| 5 | Fuzzy path recovery | S | Reduces navigation turn waste |
| 8 | KV cache stabilisation | M | Largest single perf win |
| 9 | Harden tool-call parser | M | Reduces silent parse failures |

### Phase 2 — Context Efficiency (2–4 weeks)

| # | Gap | Effort | Why second |
|---|-----|--------|------------|
| 2 | Tiered compaction + disk persistence | M | Extends effective context |
| 6 | Dynamic system prompt (git + CLAUDE.md) | M | Reduces discovery turns |
| 7 | `<thought>` block support | M | Reduces wrong-tool calls |
| 11 | Turn counter UI | S | Immediate UX improvement |

### Phase 3 — Architecture & Polish (1+ months)

| # | Gap | Effort | Why last |
|---|-----|--------|----------|
| 9 | Migrate to JSON tool calls | L | ✅ Completed |
| 12 | Sub-agent specialisation | M | ✅ Completed |
| 13 | Session persistence / resume | L | ✅ Completed |
| 10 | Secret scanning | S | ✅ Completed |
| 14 | Background memory consolidation | XL | ✅ Completed (Simplified) |

---

## What Claude Code Does That CyberPaw Should **Not** Copy

| Feature | Reason to skip |
|---------|----------------|
| **LLM summarisation during compaction** | Costs a full inference pass. On a 4B local model this takes 10–30 seconds and may produce worse summaries than simple truncation. |
| **USD cost tracking** | No API cost for local inference. Turn count is the meaningful budget. |
| **Session history pagination** | Requires persistent storage and a replay mechanism. The 8 192-token window makes most sessions too short to need resumption. |
| **Coordinator / Swarm mode** | Designed for parallel cloud agents. On a single local GPU, running two agents concurrently would halve throughput. Sequential sub-agents are the right model. |
| **KAIROS (always-on proactive assistant)** | Requires background inference. Drains battery and blocks the GPU for interactive use. |
| **ULTRAPLAN (remote Opus session)** | Requires Anthropic API. Antithetical to CyberPaw's offline-first design. |
| **IDE bridge / LSP integration** | Out of scope for a standalone desktop app. |
| **Undercover mode** | Internal Anthropic tooling. Not applicable. |
