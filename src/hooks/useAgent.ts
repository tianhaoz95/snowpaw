/**
 * useAgent — Tauri event listener + command dispatcher
 *
 * Bridges the Tauri IPC layer to the Terminal component.
 * Listens on "agent://stream" events and routes each NDJSON message
 * to the appropriate handler (token display, tool UI, permission dialog).
 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";

// ── Diff rendering ────────────────────────────────────────────────────────────

const DIFF_MAX_LINES = 40; // max lines shown per hunk before truncating
const RED   = "\x1b[38;2;255;100;100m";
const GREEN = "\x1b[38;2;100;220;100m";
const DIM   = "\x1b[2m";
const RESET = "\x1b[0m";

/**
 * Render a unified-style diff between old_string and new_string as an ANSI
 * string ready to write to the xterm terminal.
 */
function formatDiff(oldStr: string, newStr: string): string {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");
  const lines: string[] = [];

  // Simple LCS-based diff using Myers-style patience diff approximation.
  // For the sizes we deal with (small edits) a straightforward approach works.
  const lcs = computeLCS(oldLines, newLines);

  let oi = 0, ni = 0, li = 0;
  while (oi < oldLines.length || ni < newLines.length) {
    if (li < lcs.length && oi === lcs[li][0] && ni === lcs[li][1]) {
      // Context line (unchanged)
      lines.push(`${DIM} ${oldLines[oi]}${RESET}`);
      oi++; ni++; li++;
    } else if (oi < oldLines.length && (li >= lcs.length || oi < lcs[li][0])) {
      lines.push(`${RED}-${oldLines[oi]}${RESET}`);
      oi++;
    } else {
      lines.push(`${GREEN}+${newLines[ni]}${RESET}`);
      ni++;
    }
  }

  // Trim context: keep only lines that are adjacent to a change.
  const changed = new Set<number>();
  lines.forEach((l, i) => { if (l.startsWith(RED) || l.startsWith(GREEN)) changed.add(i); });
  const CONTEXT = 2;
  const keep = new Set<number>();
  changed.forEach((i) => {
    for (let d = -CONTEXT; d <= CONTEXT; d++) {
      const idx = i + d;
      if (idx >= 0 && idx < lines.length) keep.add(idx);
    }
  });

  const filtered: string[] = [];
  let lastKept = -1;
  [...keep].sort((a, b) => a - b).forEach((i) => {
    if (lastKept >= 0 && i > lastKept + 1) filtered.push(`${DIM}  ···${RESET}`);
    filtered.push(lines[i]);
    lastKept = i;
  });

  // Truncate if huge
  const out = filtered.length > DIFF_MAX_LINES
    ? [...filtered.slice(0, DIFF_MAX_LINES), `${DIM}  … (${filtered.length - DIFF_MAX_LINES} more lines)${RESET}`]
    : filtered;

  return out.map((l) => l.replace(/\n/g, "")).join("\r\n") + "\r\n";
}

/** Compute LCS indices: returns array of [oldIdx, newIdx] pairs. */
function computeLCS(a: string[], b: string[]): [number, number][] {
  // For large inputs fall back to no-context diff to avoid O(n²) hang.
  if (a.length * b.length > 10_000) return [];
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
  const result: [number, number][] = [];
  let i = m, j = n;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) { result.unshift([i - 1, j - 1]); i--; j--; }
    else if (dp[i - 1][j] >= dp[i][j - 1]) i--;
    else j--;
  }
  return result;
}

// ── Tool display formatting ────────────────────────────────────────────────────

// ANSI color codes per tool category
// Cyberpunk pink/purple palette — all tool colors use the hot-pink/violet range
const TOOL_COLORS: Record<string, string> = {
  // File reads — soft violet
  Read:       "\x1b[38;2;204;153;255m",
  Glob:       "\x1b[38;2;204;153;255m",
  Grep:       "\x1b[38;2;204;153;255m",
  ListDir:    "\x1b[38;2;204;153;255m",
  // File writes — hot pink
  Write:      "\x1b[38;2;255;45;152m",
  Edit:       "\x1b[38;2;255;45;152m",
  MultiEdit:  "\x1b[38;2;255;45;152m",
  Move:       "\x1b[38;2;255;45;152m",
  DeleteFile: "\x1b[38;2;255;80;80m",
  // Shell / execution — electric magenta
  Bash:       "\x1b[38;2;255;0;200m",
  REPL:       "\x1b[38;2;255;0;200m",
  // Sleep — dim pink
  Sleep:      "\x1b[38;2;180;80;140m",
  // Web — neon purple
  WebFetch:   "\x1b[38;2;170;0;255m",
  WebSearch:  "\x1b[38;2;170;0;255m",
  // Sub-agent — bright pink-white
  Agent:      "\x1b[38;2;255;160;220m",
  // Task & project management — pink-gold
  TodoWrite:   "\x1b[38;2;255;130;180m",
  TaskCreate:  "\x1b[38;2;255;130;180m",
  TaskGet:     "\x1b[38;2;255;130;180m",
  TaskList:    "\x1b[38;2;255;130;180m",
  TaskUpdate:  "\x1b[38;2;255;130;180m",
  TaskStop:    "\x1b[38;2;255;80;80m",
  TaskOutput:  "\x1b[38;2;255;130;180m",
};

function formatToolStart(
  tool: string,
  input: Record<string, unknown>,
): { color: string; summary: string } {
  const color = TOOL_COLORS[tool] ?? "\x1b[96m";  // default: bright cyan

  let summary = "";
  switch (tool) {
    case "Read": {
      const p = shorten(input.file_path as string);
      const off = input.offset ? `:${input.offset}` : "";
      const lim = input.limit ? `+${input.limit}` : "";
      summary = `${p}${off}${lim}`;
      break;
    }
    case "Write":
      summary = shorten(input.file_path as string);
      break;
    case "Edit": {
      const p = shorten(input.file_path as string);
      const old = String(input.old_string ?? "").split("\n")[0].slice(0, 40);
      summary = `${p}  "${old}"`;
      break;
    }
    case "Glob":
      summary = `${input.pattern}${input.path ? `  in ${shorten(input.path as string)}` : ""}`;
      break;
    case "Grep":
      summary = `/${input.pattern}/${input.glob ? `  ${input.glob}` : ""}`;
      break;
    case "ListDir":
      summary = shorten((input.path as string) || ".");
      break;
    case "Bash": {
      const cmd = String(input.command ?? "");
      summary = cmd.length > 80 ? cmd.slice(0, 80) + "…" : cmd;
      break;
    }
    case "REPL": {
      const desc = String(input.description ?? "");
      const firstLine = String(input.code ?? "").split("\n")[0];
      summary = desc || (firstLine.length > 80 ? firstLine.slice(0, 80) + "…" : firstLine);
      break;
    }
    case "Sleep":
      summary = `${input.seconds}s`;
      break;
    case "WebFetch": {
      const hint = String(input.prompt ?? "");
      summary = shorten(input.url as string) + (hint ? `  — ${hint.slice(0, 40)}` : "");
      break;
    }
    case "WebSearch":
      summary = String(input.query ?? "");
      break;
    case "Agent":
      summary = String(input.description ?? input.prompt ?? "").slice(0, 60);
      break;
    case "TodoWrite": {
      const todos = (input.todos as Array<{ text: string; done?: boolean }>) ?? [];
      const done = todos.filter((t) => t.done).length;
      summary = `${todos.length} todos (${done} done)`;
      break;
    }
    case "TaskCreate":
      summary = String(input.subject ?? "").slice(0, 60);
      break;
    case "TaskGet":
    case "TaskStop":
    case "TaskOutput":
      summary = `#${input.id}`;
      break;
    case "TaskList":
      summary = input.status_filter && input.status_filter !== "all"
        ? `filter: ${input.status_filter}`
        : "all tasks";
      break;
    case "TaskUpdate": {
      const parts: string[] = [`#${input.id}`];
      if (input.status) parts.push(`→ ${input.status}`);
      if (input.subject) parts.push(String(input.subject).slice(0, 40));
      summary = parts.join("  ");
      break;
    }
    default: {
      // Generic: show first key=value pair
      const first = Object.entries(input)[0];
      summary = first ? `${first[0]}=${String(first[1]).slice(0, 60)}` : "";
    }
  }

  return { color, summary };
}

function shorten(p: string): string {
  if (!p) return "";
  // Replace $HOME with ~
  const home = (window as unknown as Record<string, string>).__HOME__ ?? "";
  if (home && p.startsWith(home)) p = "~" + p.slice(home.length);
  // Show only last 3 path segments if long
  const parts = p.replace(/\\/g, "/").split("/");
  return parts.length > 4 ? "…/" + parts.slice(-3).join("/") : p;
}

export type AgentPhase = "idle" | "thinking" | "tool_running";

export interface ModelStatus {
  backend: string;
  loaded: boolean;
  vramUsedMb: number;
  modelSizeMb: number;
  kvCacheMb: number;
}

export interface GenerationStats {
  totalTokens: number;
  tokensPerSec: number;
}

export interface PendingPermission {
  id: string;
  tool: string;
  input: Record<string, unknown>;
}

export interface DownloadProgress {
  modelId: string;
  pct: number;
  downloadedMb: number;
  totalMb: number | null;
  speedMbps: number;
  resuming?: boolean;
}

export interface ModelCatalogEntry {
  id: string;
  name: string;
  description: string;
  filename: string;
  size_gb: number;
  quant: string;
  requires_hf_token: boolean;
}

export function useAgent(onConfigUpdate?: (patch: Partial<import("./useConfig").AppConfig>) => void) {
  const [agentPhase, setAgentPhase] = useState<AgentPhase>("idle");
  const [modelStatus, setModelStatus] = useState<ModelStatus>({
    backend: "unknown",
    loaded: false,
    vramUsedMb: 0,
    modelSizeMb: 0,
    kvCacheMb: 0,
  });
  const [pendingPermission, setPendingPermission] =
    useState<PendingPermission | null>(null);
  const [loadProgress, setLoadProgress] = useState<{
    pct: number; backend: string; heartbeat?: boolean;
  } | null>(null);
  // True while a load is in flight — prevents status poll responses from
  // re-triggering the progress bar after loading completes.
  const modelLoadingRef = useRef(false);
  const [downloadProgress, setDownloadProgress] =
    useState<DownloadProgress | null>(null);
  const [downloadedModelPath, setDownloadedModelPath] = useState<string | null>(null);
  const [modelCatalog, setModelCatalog] = useState<ModelCatalogEntry[]>([]);
  const [generationStats, setGenerationStats] = useState<GenerationStats>({
    totalTokens: 0,
    tokensPerSec: 0,
  });

  // Ref to the terminal's write function — set by Terminal via callback
  const writeToTerminalRef = useRef<((text: string) => void) | null>(null);

  const write = useCallback((text: string) => {
    writeToTerminalRef.current?.(text);
  }, []);

  // ── Event listener ──────────────────────────────────────────────────────────
  useEffect(() => {
    const unlisten = listen<string>("agent://stream", (event) => {
      const raw = event.payload;
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(raw);
      } catch {
        write(raw + "\r\n");
        return;
      }

      const type = msg.type as string;

      if (type === "token") {
        // Stream token directly to terminal — convert \n to \r\n for xterm
        const text = (msg.text as string).replace(/\n/g, "\r\n");
        write(text);
      } else if (type === "tool_start") {
        const tool = msg.tool as string;
        const input = (msg.input as Record<string, unknown>) ?? {};
        const label = msg.agent_label ? `\x1b[2m[${msg.agent_label}]\x1b[0m ` : "";
        const { color, summary } = formatToolStart(tool, input);
        write(`\r\n${label}${color}┌ ${tool}\x1b[0m \x1b[2m${summary}\x1b[0m\r\n`);
        // Render inline diff for Edit and MultiEdit
        if (tool === "Edit") {
          const oldStr = String(input.old_string ?? "");
          const newStr = String(input.new_string ?? "");
          if (oldStr || newStr) write(formatDiff(oldStr, newStr));
        } else if (tool === "MultiEdit") {
          const edits = (input.edits as Array<{ old_string: string; new_string: string }>) ?? [];
          for (const e of edits) {
            if (e.old_string || e.new_string) write(formatDiff(e.old_string ?? "", e.new_string ?? ""));
          }
        }
      } else if (type === "tool_end") {
        const tool = msg.tool as string;
        const isError = msg.is_error as boolean;
        const summary = (msg.summary as string) ?? "";
        const label = msg.agent_label ? `\x1b[2m[${msg.agent_label}]\x1b[0m ` : "";
        const { color } = formatToolStart(tool, {});
        const statusIcon = isError ? "\x1b[31m✗\x1b[0m" : "\x1b[32m✓\x1b[0m";
        const resultText = summary.length > 120 ? summary.slice(0, 120) + "…" : summary;
        write(`${label}${color}└\x1b[0m ${statusIcon} \x1b[2m${resultText}\x1b[0m\r\n`);
      } else if (type === "tool_ask") {
        setPendingPermission({
          id: msg.id as string,
          tool: msg.tool as string,
          input: (msg.input as Record<string, unknown>) ?? {},
        });
      } else if (type === "status") {
        const phase = (msg.phase as AgentPhase) ?? "idle";
        setAgentPhase((prev) => {
          if (phase === "idle" && prev !== "idle") {
            write("\r\n\x1b[38;2;255;45;152m❯\x1b[0m ");
          }
          return phase;
        });
      } else if (type === "system") {
        write(`\x1b[2K\r\x1b[38;2;220;130;220m${msg.text}\x1b[0m\r\n`);
      } else if (type === "error") {
        write(`\r\n\x1b[38;2;255;80;80mError: ${msg.message}\x1b[0m\r\n`);
        write("\x1b[38;2;255;45;152m❯\x1b[0m ");
        setAgentPhase("idle");
      } else if (type === "model_progress") {
        const backend = modelStatus.backend !== "unknown"
          ? modelStatus.backend
          : (msg.backend as string) ?? "model";
        setLoadProgress({
          pct: (msg.pct as number) ?? 0,
          backend,
          heartbeat: (msg.heartbeat as boolean) ?? false,
        });
      } else if (type === "model_status") {
        const backend = (msg.backend as string) ?? "unknown";
        if ((msg.loaded as boolean) && modelLoadingRef.current) {
          // Only set pct=100 when a load was actually in flight — not for
          // periodic status poll responses which also have loaded:true.
          modelLoadingRef.current = false;
          setLoadProgress({ pct: 100, backend });
        }
        setModelStatus({
          backend,
          loaded: (msg.loaded as boolean) ?? false,
          vramUsedMb: (msg.vram_used_mb as number) ?? 0,
          modelSizeMb: (msg.model_size_mb as number) ?? 0,
          kvCacheMb: (msg.kv_cache_mb as number) ?? 0,
        });
        // Sync auto-calculated values back to the UI config, but only for
        // fields where auto is still enabled — don't overwrite manual overrides.
        if (onConfigUpdate) {
          const patch: Partial<import("./useConfig").AppConfig> = {};
          if (msg.context_size) patch.context_size = msg.context_size as number;
          if (msg.max_new_tokens) patch.max_new_tokens = msg.max_new_tokens as number;
          if (Object.keys(patch).length > 0) onConfigUpdate(patch);
        }
      } else if (type === "generation_stats") {
        setGenerationStats((prev) => ({
          totalTokens: prev.totalTokens + ((msg.tokens as number) ?? 0),
          tokensPerSec: (msg.tokens_per_sec as number) ?? 0,
        }));
      } else if (type === "sidecar_exit") {
        write(`\r\n\x1b[31mAgent process exited (code ${msg.code}).\x1b[0m\r\n`);
        setAgentPhase("idle");
      } else if (type === "shell_output") {
        // Direct shell command output — stream as-is, converting \n to \r\n
        const text = (msg.text as string ?? "").replace(/\n/g, "\r\n");
        write(text);
      } else if (type === "shell_done") {
        const code = msg.exit_code as number;
        if (code !== 0) {
          write(`\r\n\x1b[31m[exit ${code}]\x1b[0m\r\n`);
        }
        write("\r\n\x1b[32m❯\x1b[0m ");
      } else if (type === "download_catalog") {
        setModelCatalog((msg.models as ModelCatalogEntry[]) ?? []);
      } else if (type === "download_progress") {
        setDownloadProgress({
          modelId: msg.model_id as string,
          pct: (msg.pct as number) ?? 0,
          downloadedMb: (msg.downloaded_mb as number) ?? 0,
          totalMb: (msg.total_mb as number | null) ?? null,
          speedMbps: (msg.speed_mbps as number) ?? 0,
          resuming: (msg.resuming as boolean) ?? false,
        });
      } else if (type === "download_done") {
        const path = msg.path as string;
        setDownloadProgress(null);
        setDownloadedModelPath(path);
        write(`\x1b[38;2;255;45;152mModel downloaded: ${path}\x1b[0m\r\n`);
      } else if (type === "download_error") {
        setDownloadProgress(null);
        write(`\r\n\x1b[31mDownload error: ${msg.message}\x1b[0m\r\n`);
      } else if (type === "download_cancelled") {
        setDownloadProgress(null);
        write(`\x1b[33mDownload cancelled.\x1b[0m\r\n`);
      }
    });

    return () => {
      unlisten.then((fn) => fn());
    };
  }, [write]);

  // Poll model status periodically when a model is loaded so the UI can
  // display memory usage updates. Starts when modelStatus.loaded becomes true
  // and stops when it becomes false or the component unmounts.
  useEffect(() => {
    if (!modelStatus.loaded) return;
    const id = setInterval(() => {
      invoke("get_model_status").catch(() => {});
    }, 10_000);
    return () => clearInterval(id);
  }, [modelStatus.loaded]);

  // ── Commands ────────────────────────────────────────────────────────────────

  const sendInput = useCallback(async (text: string) => {
    // "! command" — run directly as a shell command, bypass the LLM
    if (text.startsWith("!")) {
      const cmd = text.slice(1).trim();
      if (!cmd) {
        write("\x1b[32m❯\x1b[0m ");
        return;
      }
      write(`\x1b[91m$ ${cmd}\x1b[0m\r\n`);
      try {
        await invoke("run_shell_command", { command: cmd });
      } catch (e) {
        write(`\r\n\x1b[31mFailed to run: ${e}\x1b[0m\r\n`);
        write("\x1b[32m❯\x1b[0m ");
      }
      return;
    }
    try {
      await invoke("send_input", { text });
    } catch (e) {
      write(`\r\n\x1b[31mFailed to send: ${e}\x1b[0m\r\n`);
    }
  }, [write]);

  const interrupt = useCallback(async () => {
    await invoke("interrupt_agent").catch(() => {});
  }, []);

  const resetSession = useCallback(async () => {
    await invoke("reset_session").catch(() => {});
    write("\x1b[2J\x1b[H"); // clear screen
    write("\x1b[32mCyberPaw\x1b[0m — session reset.\r\n\r\n");
    write("\x1b[32m❯\x1b[0m ");
    setGenerationStats({ totalTokens: 0, tokensPerSec: 0 });
  }, [write]);

  const setWorkingDirectory = useCallback(async (path: string, silent = false) => {
    await invoke("set_working_directory", { path }).catch(() => {});
    if (!silent) write(`\x1b[33mOpened: ${path}\x1b[0m\r\n`);
  }, [write]);

  const resolvePermission = useCallback(
    async (id: string, approved: boolean) => {
      setPendingPermission(null);
      await invoke("send_tool_ack", {
        id,
        decision: approved ? "allow" : "deny",
      }).catch(() => {});
      write(
        approved
          ? `\x1b[32m✓ Approved\x1b[0m\r\n`
          : `\x1b[31m✗ Denied\x1b[0m\r\n`
      );
    },
    [write]
  );

  const loadModel = useCallback(
    async (modelPath: string, backend?: string) => {
      modelLoadingRef.current = true;
      await invoke("load_model", {
        modelPath,
        backend: backend ?? null,
      }).catch((e) => {
        modelLoadingRef.current = false;
        write(`\r\n\x1b[31mLoad model failed: ${e}\x1b[0m\r\n`);
      });
    },
    [write]
  );

  const fetchCatalog = useCallback(async () => {
    await invoke("get_download_catalog").catch(() => {});
  }, []);

  const startDownload = useCallback(
    async (modelId: string, destDir?: string, hfToken?: string) => {
      setDownloadedModelPath(null);
      await invoke("start_model_download", {
        modelId,
        destDir: destDir ?? null,
        hfToken: hfToken ?? null,
      }).catch((e) => write(`\r\n\x1b[31mDownload start failed: ${e}\x1b[0m\r\n`));
    },
    [write]
  );

  const cancelDownload = useCallback(async () => {
    await invoke("cancel_model_download").catch(() => {});
  }, []);

  const installBrowser = useCallback(async () => {
    write("\x1b[33mStarting browser installation (Chromium)…\x1b[0m\r\n");
    await invoke("install_browser").catch((e) =>
      write(`\r\n\x1b[31mBrowser installation failed: ${e}\x1b[0m\r\n`)
    );
  }, [write]);

  return {
    sendInput,
    interrupt,
    resetSession,
    setWorkingDirectory,
    pendingPermission,
    resolvePermission,
    modelStatus,
    generationStats,
    agentPhase,
    loadProgress,
    writeToTerminal: writeToTerminalRef,
    writeTerminal: write,
    // Model loading
    loadModel,
    // Download
    fetchCatalog,
    startDownload,
    cancelDownload,
    installBrowser,
    downloadProgress,
    downloadedModelPath,
    modelCatalog,
    checkInstalledModels: async (dir: string): Promise<Set<string>> => {
      try {
        const { readDir } = await import("@tauri-apps/plugin-fs");
        const entries = await readDir(dir);
        return new Set(entries.map((e) => e.name).filter(Boolean));
      } catch {
        return new Set<string>();
      }
    },
  };
}
