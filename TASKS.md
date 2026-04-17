# CyberPaw UI Task List

---

## Task 1 — Window control buttons (close / maximize / minimize) do nothing

### Issue Description
The app uses `decorations: false` in `src-tauri/tauri.conf.json`, disabling the native OS window chrome entirely. The custom window-control buttons in `MenuBar.tsx` call `getCurrentWindow().minimize()`, `.isMaximized()`, `.maximize()`, `.unmaximize()`, and `.close()` from `@tauri-apps/api/window`. All errors are silently swallowed by `.catch(() => {})`, so the buttons appear to work but do nothing.

The root cause is that `src-tauri/capabilities/default.json` only grants `core:window:allow-start-dragging`. The five other window-manipulation permissions are missing, so Tauri rejects every call and the catch handler hides the error.

### Fix
Add the missing permissions to `src-tauri/capabilities/default.json`:

```json
"core:window:allow-minimize",
"core:window:allow-close",
"core:window:allow-maximize",
"core:window:allow-unmaximize",
"core:window:allow-is-maximized"
```

No code changes needed in the React layer — the handlers are already correct.

### Verification
1. Run `npm run tauri dev`.
2. Click **Minimize** → window should minimise to the Dock.
3. Click **Maximize** → window should expand to full screen.
4. Click **Maximize** again → window should return to normal size.
5. Click **Close** → app should quit.

---

## Task 2 — Remove LLM backend selector from Settings

### Issue Description
`src/components/Settings.tsx` renders a "LLM Backend" `<RadioGroup>` with two options: `Auto (detect memory)` and `llama.cpp (GGUF)`. Since AirLLM was removed and only llama.cpp is supported, this selector has no effect — both options result in the same behaviour. Showing it confuses users and implies a choice that does not exist.

Related code:
- `Settings.tsx` lines 152–162 — the `<Field label="LLM Backend">` block.
- `src/hooks/useConfig.ts` — `AppConfig.backend` type is `"auto" | "llamacpp"`.
- `src-tauri/src/commands.rs` — `AppConfig.backend` field is still present.

### Fix
1. **`src/components/Settings.tsx`** — delete the `<Field label="LLM Backend">…</Field>` block (lines 152–162).
2. **`src/hooks/useConfig.ts`** — remove `backend` from `AppConfig` and `DEFAULT_CONFIG`.
3. **`src-tauri/src/commands.rs`** — remove the `backend` field from the Rust `AppConfig` struct and its `Default` impl.

> The `backend` param already appears unused in the sidecar (selector always returns `LlamaCppBackend`), so removing it end-to-end is clean.

### Verification
1. Open Settings — the "LLM Backend" section should be gone.
2. Save settings and reload — no TypeScript errors, no Rust compile errors.
3. Load a model and confirm it still loads correctly (backend defaults to llamacpp implicitly).

---

## Task 3 — Fix temperature at model-recommended value; remove temperature UI

### Issue Description
`Settings.tsx` exposes a `temperature` slider (lines 202–213) and `useConfig.ts` defaults it to `0.2`. The correct values per model, sourced from each model's official `generation_config.json` on HuggingFace, are:

| Model | Recommended Temperature |
|---|---|
| Gemma 4 E2B-it / E4B-it | **1.0** |
| Qwen2.5-Coder-3B-Instruct | **0.7** |
| Qwen2.5-Coder-7B-Instruct | **0.7** |

Letting users adjust temperature freely risks degrading output quality (e.g. `0.2` makes Gemma 4 overly repetitive and terse). The current default of `0.2` is already incorrect for all catalog models.

### Fix
1. **`src/components/Settings.tsx`** — delete the `<Field label={…Temperature…}>` slider block (lines 202–213).
2. **`src/hooks/useConfig.ts`** — remove `temperature` from `AppConfig` and `DEFAULT_CONFIG`.
3. **`src-tauri/src/commands.rs`** — remove the `temperature` field from the Rust `AppConfig` struct.
4. **`agent/backends/llamacpp_backend.py`** (or wherever the model is loaded) — set temperature in the backend using a per-model lookup table keyed on filename:
   - filenames containing `gemma` → `1.0`
   - filenames containing `qwen` → `0.7`
   - fallback → `1.0`

   Alternatively, use a single hardcoded value of `1.0` (Gemma 4 is the recommended and primary model family in the catalog) with a comment explaining the source.

### Verification
1. Open Settings — the Temperature slider should be gone.
2. Load the Gemma 4 E4B model; generate a response — output should be fluent and not clipped.
3. Load a Qwen2.5-Coder model; generate a response — output should be creative and not repetitive.
4. Check the sidecar logs to confirm the temperature value passed to `llama_cpp` matches the expected value.

---

## Task 4 — Remove browser engine install UI

### Issue Description
`Settings.tsx` contains a "Browser Engine (Playwright)" section (lines 233–251) with an "Install Browser Engine (Chromium)" button. The `onInstallBrowser` prop flows through `Settings` → `App.tsx` → `useAgent.ts` → Tauri `install_browser` command → sidecar `install_browsers` message. This feature is not yet supported and showing the button misleads users into clicking it with no working outcome.

Related files:
- `src/components/Settings.tsx` lines 233–251 — the UI block.
- `src/App.tsx` — passes `onInstallBrowser` prop to `<Settings>`.
- `src/hooks/useAgent.ts` — `installBrowser()` function.
- `src-tauri/src/commands.rs` — `install_browser` Tauri command.

### Fix
1. **`src/components/Settings.tsx`** — delete the `<Field label="Browser Engine (Playwright)">…</Field>` block and the `onInstallBrowser` prop from the `Props` interface and the function signature.
2. **`src/App.tsx`** — remove the `onInstallBrowser` prop passed to `<Settings>`.
3. Leave `useAgent.ts` and `commands.rs` in place (keeping backend plumbing for future use) — only the UI surface is removed.

### Verification
1. Open Settings — "Browser Engine (Playwright)" section should be absent.
2. No TypeScript errors (`npm run build` should pass).
3. Network-access checkbox and all other settings should still function normally.

---

## Task 5 — Remove additional system prompt UI

### Issue Description
`Settings.tsx` renders an "Additional System Prompt" `<textarea>` (lines 255–263) that appends a user-defined string to the default system prompt. The feature is not wanted at this time. The field is still wired up through `AppConfig.system_prompt_append` → `useConfig.ts` → `commands.rs` → sidecar config.

### Fix
1. **`src/components/Settings.tsx`** — delete the `<Field label="Additional System Prompt">…</Field>` block (lines 255–263).
2. **`src/hooks/useConfig.ts`** — remove `system_prompt_append` from `AppConfig` and `DEFAULT_CONFIG`.
3. **`src-tauri/src/commands.rs`** — remove `system_prompt_append` from the Rust `AppConfig` struct and its `Default` impl.
4. **Sidecar** — find where `system_prompt_append` is consumed in `agent/` (likely in `agent/harness/` or `agent/main.py`) and remove that logic, making the system prompt non-extensible from config.

### Verification
1. Open Settings — "Additional System Prompt" textarea should be gone.
2. `npm run build` and `cargo build` (inside `src-tauri/`) both pass without errors.
3. Load a model and send a message — the agent should respond normally using only the default system prompt.
