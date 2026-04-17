# CyberPaw — UI Testing Design Document

> Automated UI-level testing with Playwright for a Tauri + React + xterm.js desktop app.

---

## 1. Problem Statement

CyberPaw has no frontend test coverage. Changes to components (MenuBar, Settings, Terminal, PermissionDialog, ModelDownloader) are validated only by manual inspection. As the codebase grows, regressions in UI behaviour are increasingly likely. We need an automated UI testing layer that:

- Runs on a developer's MacBook (the primary development environment).
- Exercises real browser rendering and real user interactions (click, type, keyboard).
- Mocks out Tauri IPC and the Python sidecar so tests are fast and deterministic.
- Can be extended to full-binary smoke tests in CI.

---

## 2. Key Constraints

### 2.1 `tauri-driver` does not support macOS

Tauri's official WebDriver bridge (`tauri-driver`) works by wrapping the platform's native WebDriver server. On macOS, WKWebView has no WebDriver tool; `tauri-driver` only supports Windows (EdgeDriver) and Linux (WebKitWebDriver). **The real Tauri binary cannot be driven by WebDriver on macOS.**

### 2.2 Vite dev server is accessible as a plain browser page

`tauri.conf.json` sets `devUrl: "http://localhost:1420"`. When `npm run dev` is running, the full React app is available in any browser at that URL. The only thing missing is `window.__TAURI_INTERNALS__`, which Tauri normally injects via its webview initialisation scripts.

### 2.3 xterm.js renders to a canvas

`Terminal.tsx` uses `@xterm/xterm` which renders into a `<canvas>`. Standard DOM text assertions (`toContainText`) cannot read terminal output. Testing the terminal requires:
- Typing via `page.keyboard.type()` / `press()`.
- Asserting on side-effects (IPC calls triggered, ANSI sequences written to the terminal buffer) rather than the canvas content.
- Or attaching a custom data attribute / accessibility hook to the container for testability.

### 2.4 Tauri IPC is not available in the browser

`invoke()` and `listen()` from `@tauri-apps/api` call `window.__TAURI_INTERNALS__.invoke`, which only exists inside a Tauri webview. In a plain browser, these throw immediately. All Tauri IPC must be mocked before the app code runs.

---

## 3. Testing Strategy — Three Layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Layer 3 — Binary smoke tests          (Linux CI only, tauri-driver)    │
│  Full Tauri binary, real sidecar stub, WebKitWebDriver on GitHub Actions│
├─────────────────────────────────────────────────────────────────────────┤
│  Layer 2 — Full-app E2E tests          (macOS + CI, Playwright browser) │
│  Vite dev server @ localhost:1420, all Tauri IPC mocked via initScript  │
├─────────────────────────────────────────────────────────────────────────┤
│  Layer 1 — Component tests             (macOS + CI, Playwright CT)      │
│  Individual React components mounted in isolation, props fully controlled│
└─────────────────────────────────────────────────────────────────────────┘
```

**Layer 1 is the primary investment.** It is fast, hermetic, and cross-platform. Layer 2 catches cross-component regressions. Layer 3 is a safety net for binary packaging issues.

---

## 4. Architecture

### 4.1 Layer 1 — Playwright Component Testing (`@playwright/experimental-ct-react`)

Playwright CT spins up a Vite-based harness, mounts individual React components into a real Chromium page, and provides a Playwright `Locator` API for assertions. It does **not** launch the Tauri binary.

```
tests/ct/
├── playwright-ct.config.ts       # CT-specific Playwright config
├── playwright/
│   ├── index.html                # Mount host — required by Playwright CT
│   └── index.ts                  # Global setup: mock __TAURI_INTERNALS__
├── MenuBar.spec.tsx
├── Settings.spec.tsx
├── PermissionDialog.spec.tsx
├── ModelDownloader.spec.tsx
└── ModelLoadProgress.spec.tsx
```

The `playwright/index.ts` file runs inside the browser before each test. It installs a minimal `window.__TAURI_INTERNALS__` stub so that any component that imports `@tauri-apps/api` does not crash:

```ts
// playwright/index.ts
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";
import { randomFillSync } from "crypto";

// jsdom polyfill — crypto must exist before Tauri's UUID helpers run
Object.defineProperty(window, "crypto", {
  value: { getRandomValues: (b: Uint8Array) => randomFillSync(b) },
});

mockWindows("main");

// Default IPC: return a sensible no-op for every command
mockIPC((cmd) => {
  if (cmd === "get_config")   return { working_directory: "~", model_path: "", context_size: 8192, max_new_tokens: 2048, permission_mode: "ask", network_enabled: false };
  if (cmd === "set_config")   return;
  if (cmd === "send_input")   return;
  if (cmd === "load_model")   return;
  if (cmd === "get_download_catalog") return;
});
```

Individual tests override `mockIPC` to simulate specific responses.

### 4.2 Layer 2 — Playwright E2E against Vite

```
tests/e2e/
├── playwright.config.ts          # E2E config; webServer: npm run dev
├── fixtures/
│   └── tauri-mock.ts             # page.addInitScript factory
├── settings.spec.ts
├── menubar.spec.ts
└── permission-flow.spec.ts
```

`playwright.config.ts` starts the Vite dev server automatically:

```ts
webServer: {
  command: "npm run dev",
  url: "http://localhost:1420",
  reuseExistingServer: true,
},
```

A shared fixture injects the Tauri mock before every page load:

```ts
// fixtures/tauri-mock.ts
export async function installTauriMock(page: Page, overrides?: Record<string, unknown>) {
  await page.addInitScript({
    path: "tests/e2e/fixtures/tauri-ipc-mock.js",  // bundled UMD stub
  });
  if (overrides) {
    await page.addInitScript(`window.__TEST_IPC_OVERRIDES__ = ${JSON.stringify(overrides)}`);
  }
}
```

`tauri-ipc-mock.js` is a small bundle that defines `window.__TAURI_INTERNALS__` and routes `invoke()` calls through a configurable map. It is built once during test setup.

### 4.3 Layer 3 — tauri-driver on Linux CI (future)

This layer is documented for future implementation. It runs in GitHub Actions on an Ubuntu runner only.

```yaml
# .github/workflows/e2e-linux.yml
- name: Install WebKitWebDriver
  run: sudo apt-get install -y webkit2gtk-driver
- name: Install tauri-driver
  run: cargo install tauri-driver --locked
- name: Build app
  run: npm run tauri build
- name: Run WebDriver tests
  run: npx playwright test tests/webdriver/
  env:
    CI: "true"
```

The WebDriver tests use `wdio` or the Playwright WebDriver protocol pointed at `tauri-driver` on port 4444.

---

## 5. Tauri IPC Mock Design

All IPC in CyberPaw flows through two `@tauri-apps/api` primitives:
- `invoke(cmd, args)` — calls a Tauri command.
- `listen(event, handler)` — subscribes to an event emitted by the Rust core.

The mock must implement both. A production-quality IPC mock:

```ts
// tests/support/ipc-mock.ts
import { mockIPC } from "@tauri-apps/api/mocks";
import { emit } from "@tauri-apps/api/event";

export interface MockSidecar {
  /** Call to simulate the sidecar emitting an agent://stream event. */
  emitAgentToken(text: string): Promise<void>;
  emitModelLoaded(backend: string): Promise<void>;
  emitPermissionRequest(id: string, tool: string, input: unknown): Promise<void>;
}

export function installMockSidecar(
  ipcResponses: Record<string, unknown> = {}
): MockSidecar {
  mockIPC((cmd, args) => {
    if (cmd in ipcResponses) return ipcResponses[cmd];
    // Defaults
    const defaults: Record<string, unknown> = {
      get_config: {
        working_directory: "/tmp",
        model_path: "",
        context_size: 8192,
        max_new_tokens: 2048,
        permission_mode: "ask",
        network_enabled: false,
      },
      set_config: undefined,
      send_input: undefined,
      load_model: undefined,
      reset_session: undefined,
      interrupt_agent: undefined,
      get_download_catalog: undefined,
      start_model_download: undefined,
      cancel_model_download: undefined,
    };
    return defaults[cmd];
  }, { shouldMockEvents: true });

  return {
    emitAgentToken: (text) => emit("agent://stream", { type: "token", text }),
    emitModelLoaded: (backend) => emit("agent://stream", { type: "status", backend, loaded: true, vram_used_mb: 0 }),
    emitPermissionRequest: (id, tool, input) => emit("agent://stream", { type: "permission_request", id, tool, input }),
  };
}
```

---

## 6. Component Test Inventory

### 6.1 MenuBar

| Test ID | Description | Assertions |
|---|---|---|
| `MB-01` | Renders app name "CyberPaw" | `toContainText("CyberPaw")` |
| `MB-02` | Phase indicator shows "idle" initially | badge text matches "idle" |
| `MB-03` | Phase indicator changes to "thinking…" | update `agentPhase` prop → text matches |
| `MB-04` | "Open" button calls `onOpenFolder` | spy on prop callback |
| `MB-05` | "New" button calls `onNewSession` | spy on prop callback |
| `MB-06` | Settings gear button calls `onOpenSettings` | spy on prop callback |
| `MB-07` | "no model" badge shown when `modelStatus.loaded = false` | text / style check |
| `MB-08` | Backend name shown when model is loaded | `modelStatus.loaded = true, backend = "llamacpp"` |
| `MB-09` | Minimize button click calls `getCurrentWindow().minimize` | spy on `window.__TAURI_INTERNALS__` |
| `MB-10` | Close button click calls `getCurrentWindow().close` | spy on `window.__TAURI_INTERNALS__` |

### 6.2 Settings Panel

| Test ID | Description | Assertions |
|---|---|---|
| `ST-01` | Renders "Settings" heading | `toContainText("Settings")` |
| `ST-02` | Working directory input reflects config | `inputValue` matches `config.working_directory` |
| `ST-03` | Model path input reflects config | `inputValue` matches `config.model_path` |
| `ST-04` | Cancel button calls `onClose` | spy |
| `ST-05` | Save button calls `onSave` with current draft | spy + verify args |
| `ST-06` | Changing model path field updates draft | type into input → Save → check onSave arg |
| `ST-07` | "Download a model…" toggles ModelDownloader | click button → downloader visible |
| `ST-08` | Click outside panel calls `onClose` | click backdrop overlay |
| `ST-09` | Permission mode radio changes | click "Auto-approve reads" → onSave has `permission_mode: "auto_read"` |
| `ST-10` | Network access checkbox toggles | click → Save → verify `network_enabled: true` |

### 6.3 PermissionDialog

| Test ID | Description | Assertions |
|---|---|---|
| `PD-01` | Renders tool name in heading | `toContainText(permission.tool)` |
| `PD-02` | Renders truncated input JSON | `pre` text contains JSON keys |
| `PD-03` | "Allow" button calls `onResolve(id, true)` | spy on onResolve |
| `PD-04` | "Deny" button calls `onResolve(id, false)` | spy on onResolve |
| `PD-05` | Long input is truncated at 400 chars | generate 600-char JSON; assert `…` in pre text |
| `PD-06` | Auto-deny hint text is visible | `toContainText("auto-deny in 5 min")` |

### 6.4 ModelDownloader

| Test ID | Description | Assertions |
|---|---|---|
| `MD-01` | Calls `onFetchCatalog` on mount when catalog empty | spy called once |
| `MD-02` | Renders catalog entries | pass `catalog` prop → model names visible |
| `MD-03` | Selecting a model highlights it | click model card → selection state |
| `MD-04` | "Download" button calls `onStart` with selected id | spy |
| `MD-05` | Progress bar appears when `progress` prop is set | progress element visible |
| `MD-06` | "Use this model" appears when `downloadedPath` is set | button visible |
| `MD-07` | "Use this model" calls `onUseModel` with path | spy |
| `MD-08` | "Cancel" button calls `onCancel` | spy |

### 6.5 ModelLoadProgress

| Test ID | Description | Assertions |
|---|---|---|
| `LP-01` | Not visible when `progress` is null | element not rendered / `not.toBeVisible()` |
| `LP-02` | Shows stage and percent when loading | pass progress prop → text visible |
| `LP-03` | Shows "100%" when complete | `progress = { stage: "done", pct: 100 }` |

---

## 7. E2E Test Inventory (Layer 2)

These run against the full React app on the Vite dev server, with Tauri IPC mocked via `addInitScript`.

| Test ID | Description | Precondition | Steps | Assertions |
|---|---|---|---|---|
| `E2E-01` | Initial "no model" state | no model_path in localStorage | load page | Terminal shows "No model loaded" |
| `E2E-02` | Settings panel opens and closes | – | click gear icon → click Cancel | Settings panel not in DOM |
| `E2E-03` | Saving a new model path persists | – | open Settings, type path, Save | localStorage `cyberpaw_config` has new path; `set_config` IPC called |
| `E2E-04` | PermissionDialog appears on event | model loaded | emit `permission_request` event | Dialog visible; tool name shown |
| `E2E-05` | Approving permission resolves it | dialog open | click Allow | `send_tool_ack` IPC called with `decision: "approve"` |
| `E2E-06` | Denying permission resolves it | dialog open | click Deny | `send_tool_ack` IPC called with `decision: "deny"` |
| `E2E-07` | New Session resets conversation | – | click New → confirm via resetSession IPC | `reset_session` IPC called |
| `E2E-08` | Model loading spinner appears | model_path in localStorage, load is slow | page load | Spinner characters visible in terminal DOM area |

---

## 8. Terminal Testability Approach

`xterm.js` renders into `<canvas>` elements, making `toContainText()` useless for terminal output. Use these strategies:

### 8.1 Wrapper data attribute

Add `data-testid="terminal-container"` to the outermost `<div>` in `Terminal.tsx`. This allows Playwright to locate the terminal container and interact with it via keyboard.

### 8.2 Keyboard simulation

To simulate user typing, focus the terminal container and use `page.keyboard.type()`:

```ts
await page.locator('[data-testid="terminal-container"]').click();
await page.keyboard.type("hello");
await page.keyboard.press("Enter");
```

Assert the side-effect: the `send_input` IPC mock should have been called with `{ text: "hello\n" }`.

### 8.3 Buffer inspection via exposed window variable

In test/dev builds, expose `window.__TERM_BUFFER__` by adding a small hook in `Terminal.tsx` (gated on `import.meta.env.DEV`):

```ts
if (import.meta.env.DEV) {
  (window as any).__TERM_BUFFER__ = () => term.buffer.active;
}
```

Playwright can then read terminal content:

```ts
const lines = await page.evaluate(() => {
  const buf = (window as any).__TERM_BUFFER__?.();
  return Array.from({ length: buf.length }, (_, i) => buf.getLine(i)?.translateToString().trim());
});
expect(lines).toContain("No model loaded — open Settings to load one.");
```

---

## 9. Implementation Plan

### Phase 1 — Layer 1: Component Tests

**Step 1.1 — Install Playwright Component Testing**

```bash
npm install --save-dev @playwright/experimental-ct-react playwright
npx playwright install chromium
```

**Step 1.2 — Scaffold CT config**

Create `playwright-ct.config.ts` at the repo root:

```ts
import { defineConfig, devices } from "@playwright/experimental-ct-react";

export default defineConfig({
  testDir: "tests/ct",
  snapshotDir: "tests/ct/__snapshots__",
  timeout: 10_000,
  use: {
    ctPort: 3100,
    ctViteConfig: {
      resolve: {
        alias: { "@tauri-apps/api": "./tests/support/tauri-api-shim.ts" },
      },
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

The `ctViteConfig` alias replaces `@tauri-apps/api` with a local shim that returns no-ops unless overridden by the test. This is simpler than the `mockIPC` approach for pure component tests where no IPC calls are expected.

**Step 1.3 — Create the Tauri shim**

`tests/support/tauri-api-shim.ts` — stubs out `invoke`, `listen`, `getCurrentWindow`, etc.:

```ts
export const invoke = async (_cmd: string, _args?: unknown) => undefined;
export const listen = async (_event: string, _handler: unknown) => () => {};
// Re-export from @tauri-apps/api/mocks so tests can call mockIPC:
export { mockIPC, mockWindows } from "@tauri-apps/api/mocks";
```

**Step 1.4 — Create `playwright/index.ts`**

```ts
// tests/ct/playwright/index.ts
// Runs in-browser before every CT test
import { randomFillSync } from "crypto";
Object.defineProperty(window, "crypto", {
  value: { getRandomValues: (b: Uint8Array) => randomFillSync(b) },
});
```

**Step 1.5 — Write component test files**

One file per component:
- `tests/ct/MenuBar.spec.tsx`
- `tests/ct/Settings.spec.tsx`
- `tests/ct/PermissionDialog.spec.tsx`
- `tests/ct/ModelDownloader.spec.tsx`
- `tests/ct/ModelLoadProgress.spec.tsx`

Add npm script:

```json
"test:ct": "playwright test --config playwright-ct.config.ts"
```

---

### Phase 2 — Layer 2: E2E against Vite

**Step 2.1 — Install Playwright E2E**

```bash
npm install --save-dev @playwright/test
npx playwright install chromium
```

(If already installed in Phase 1, skip the install.)

**Step 2.2 — Create E2E config**

`playwright.config.ts` at the repo root:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 15_000,
  webServer: {
    command: "npm run dev",
    url: "http://localhost:1420",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  use: {
    baseURL: "http://localhost:1420",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

**Step 2.3 — Build and bundle the IPC mock script**

Create `tests/e2e/fixtures/tauri-ipc-mock.ts`. This file is bundled into a single `.js` by a small Vite build step before tests run, then injected via `page.addInitScript`. It must not import any Node.js modules.

```bash
npx vite build tests/e2e/fixtures/tauri-ipc-mock.ts --outDir tests/e2e/fixtures/dist
```

Add an npm script:

```json
"prebuild:e2e": "vite build tests/e2e/fixtures/tauri-ipc-mock.ts --outDir tests/e2e/fixtures/dist --lib"
"test:e2e": "npm run prebuild:e2e && playwright test --config playwright.config.ts"
```

**Step 2.4 — Create base test fixture**

`tests/e2e/fixtures/base.ts`:

```ts
import { test as base, Page } from "@playwright/test";

export const test = base.extend({
  page: async ({ page }, use) => {
    // Inject the Tauri IPC mock before the page loads any scripts
    await page.addInitScript({ path: "tests/e2e/fixtures/dist/tauri-ipc-mock.js" });
    await use(page);
  },
});
export { expect } from "@playwright/test";
```

**Step 2.5 — Add `data-testid` attributes**

Add `data-testid` attributes to key elements (only needed where CSS selectors are ambiguous):

| Element | `data-testid` |
|---|---|
| MenuBar container | `menubar` |
| Terminal outer div | `terminal-container` |
| Settings panel | `settings-panel` |
| PermissionDialog | `permission-dialog` |
| Settings gear button | `settings-btn` |
| New session button | `new-session-btn` |
| Model path input | `model-path-input` |
| Save button in Settings | `settings-save-btn` |

**Step 2.6 — Write E2E test files**

- `tests/e2e/initial-state.spec.ts`
- `tests/e2e/settings.spec.ts`
- `tests/e2e/permission-flow.spec.ts`

Add npm script:

```json
"test:e2e": "playwright test --config playwright.config.ts"
```

---

### Phase 3 — Terminal testability hook

**Step 3.1 — Add `data-testid` to Terminal container**

In `src/components/Terminal.tsx`, add `data-testid="terminal-container"` to the outer `<div>`.

**Step 3.2 — Expose buffer in dev mode**

After `term.open(containerRef.current)` succeeds, add:

```ts
if (import.meta.env.DEV || import.meta.env.MODE === "test") {
  (window as any).__CYBERPAW_TERM__ = term;
}
```

This allows Playwright tests to call:

```ts
await page.evaluate(() => (window as any).__CYBERPAW_TERM__.buffer.active.getLine(0)?.translateToString());
```

---

### Phase 4 — CI integration

**Step 4.1 — GitHub Actions workflow**

`.github/workflows/ui-tests.yml`:

```yaml
name: UI Tests
on: [push, pull_request]

jobs:
  component-tests:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npm run test:ct

  e2e-tests:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npm run test:e2e

  # Layer 3 (future): tauri-driver smoke tests on Linux
  # binary-smoke:
  #   runs-on: ubuntu-latest
  #   ...
```

---

## 10. Task List

### Task T1 — Install dependencies

**Description:** Install `@playwright/experimental-ct-react` and `@playwright/test`. Install and bundle the Chromium browser for Playwright.

**Files changed:**
- `package.json` — add `devDependencies`

**Commands:**
```bash
npm install --save-dev @playwright/experimental-ct-react @playwright/test
npx playwright install chromium
```

**Verify:** `npx playwright --version` prints a version.

---

### Task T2 — Scaffold CT harness

**Description:** Create the Playwright Component Testing config, the in-browser global setup script, and the Tauri API shim.

**Files to create:**
- `playwright-ct.config.ts`
- `tests/ct/playwright/index.html`
- `tests/ct/playwright/index.ts`
- `tests/support/tauri-api-shim.ts`

**Verify:** Running `npm run test:ct` with an empty test dir prints "no tests found" without crashing.

---

### Task T3 — Add `data-testid` attributes to components

**Description:** Add `data-testid` props to the elements listed in §9 Step 2.5 and the terminal container in §9 Step 3.1.

**Files changed:**
- `src/components/MenuBar.tsx`
- `src/components/Terminal.tsx`
- `src/components/Settings.tsx`
- `src/components/PermissionDialog.tsx`

**Verify:** In a running dev server, `document.querySelector('[data-testid="terminal-container"]')` returns the element.

---

### Task T4 — Expose terminal buffer in dev mode

**Description:** After `term.open()` in `Terminal.tsx`, assign `window.__CYBERPAW_TERM__ = term` when `import.meta.env.DEV` is true.

**Files changed:** `src/components/Terminal.tsx`

**Verify:**
```ts
// In Playwright test:
const line = await page.evaluate(() =>
  (window as any).__CYBERPAW_TERM__?.buffer.active.getLine(0)?.translateToString().trim()
);
expect(line).toBeTruthy();
```

---

### Task T5 — Write PermissionDialog component tests

**Description:** Implement all 6 tests from §6.3 (PD-01 through PD-06). This is a pure presentational component with no IPC dependencies — the easiest starting point.

**File to create:** `tests/ct/PermissionDialog.spec.tsx`

**Verify:** `npm run test:ct -- --grep PermissionDialog` passes all 6 tests (no failures, no skips).

---

### Task T6 — Write MenuBar component tests

**Description:** Implement tests MB-01 through MB-08 (pure rendering and prop callbacks). Tests MB-09 and MB-10 (window controls) require mocking `getCurrentWindow()` and should be added after T3 is complete.

**File to create:** `tests/ct/MenuBar.spec.tsx`

**Verify:** `npm run test:ct -- --grep MenuBar` passes.

---

### Task T7 — Write Settings component tests

**Description:** Implement ST-01 through ST-10. ST-07 (ModelDownloader toggle) requires `catalog` prop to be provided.

**File to create:** `tests/ct/Settings.spec.tsx`

**Verify:** `npm run test:ct -- --grep Settings` passes all 10 tests.

---

### Task T8 — Write ModelDownloader and ModelLoadProgress tests

**Description:** Implement all 8 MD tests and 3 LP tests from §6.4 and §6.5.

**Files to create:**
- `tests/ct/ModelDownloader.spec.tsx`
- `tests/ct/ModelLoadProgress.spec.tsx`

**Verify:** All new tests pass.

---

### Task T9 — Scaffold E2E harness

**Description:** Create the E2E Playwright config (`playwright.config.ts`), the IPC mock injection fixture (`tests/e2e/fixtures/`), and the base test extension.

**Files to create:**
- `playwright.config.ts`
- `tests/e2e/fixtures/tauri-ipc-mock.ts`
- `tests/e2e/fixtures/base.ts`

**Verify:** `npm run test:e2e` with an empty test dir starts Vite, loads `localhost:1420`, and exits cleanly.

---

### Task T10 — Write E2E: initial state and settings flow

**Description:** Implement E2E-01 through E2E-03 (initial state, settings open/close, model path save). These cover the most common user workflows.

**File to create:** `tests/e2e/settings.spec.ts`

**Verify:** All 3 tests pass reliably with `npm run test:e2e -- --grep settings`.

---

### Task T11 — Write E2E: permission dialog flow

**Description:** Implement E2E-04 through E2E-06 (permission request event → dialog appears → approve/deny calls IPC).

**File to create:** `tests/e2e/permission-flow.spec.ts`

**Verify:** All 3 tests pass. Retry up to 2 times to account for Vite HMR startup jitter.

---

### Task T12 — Add CI workflow

**Description:** Create `.github/workflows/ui-tests.yml` to run component tests and E2E tests on every push and pull request using `macos-latest` runners.

**File to create:** `.github/workflows/ui-tests.yml`

**Verify:** Open a draft PR → all jobs turn green in GitHub Actions. Artifact output includes Playwright HTML report.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| xterm.js canvas makes terminal output unreadable | High | Use `window.__CYBERPAW_TERM__` buffer hook (§8.3) and keyboard-event + IPC-spy approach |
| `@tauri-apps/api` throws before shim loads | Medium | Use `ctViteConfig` alias to replace the entire module at bundle time |
| Vite dev server not ready when E2E tests start | Medium | `webServer.timeout: 30_000` + `reuseExistingServer` in playwright config |
| IPC mock state leaks between tests | Medium | Call `clearMocks()` from `@tauri-apps/api/mocks` in `afterEach` |
| `shouldMockEvents` (needed for `listen()`) requires `@tauri-apps/api ≥ 2.7.0` | Low | Pin `@tauri-apps/api@^2.7.0` in devDependencies |
| macOS Gatekeeper blocks Chromium first run | Low | Run `npx playwright install --with-deps chromium` which sets correct permissions |

---

## 12. Success Criteria

- `npm run test:ct` runs in < 30 seconds and covers all 27 component-level test cases.
- `npm run test:e2e` runs in < 60 seconds (Vite startup included) and covers 8 E2E flows.
- All tests pass on a cold macOS developer machine (`npm ci && npm run test:ct && npm run test:e2e`).
- CI passes on `macos-latest` GitHub Actions runner without any environment-specific setup beyond `npm ci`.
- No Tauri binary or Python sidecar is required to run either test suite.
