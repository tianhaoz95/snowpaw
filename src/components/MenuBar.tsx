/**
 * MenuBar — top navigation bar (40px)
 * Cyberpunk black + pink theme.
 */

import { getCurrentWindow } from "@tauri-apps/api/window";
import type { AgentPhase, GenerationStats, ModelStatus } from "../hooks/useAgent";

interface Props {
  agentPhase: AgentPhase;
  modelStatus: ModelStatus;
  generationStats: GenerationStats;
  workingDirectory?: string;
  onOpenFolder: () => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
}

const PHASE_COLOR: Record<AgentPhase, string> = {
  idle:        "#ff2d98",
  thinking:    "#cc00ff",
  tool_running:"#aa44ff",
};

const PHASE_LABEL: Record<AgentPhase, string> = {
  idle:        "idle",
  thinking:    "thinking…",
  tool_running:"running tool…",
};

function handleDragStart(e: React.MouseEvent) {
  if (e.button !== 0) return;
  const target = e.target as HTMLElement;
  if (target.closest("button")) return;
  e.preventDefault();
  getCurrentWindow().startDragging().catch(() => {});
}

function shortenPath(p: string): string {
  const parts = p.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : p;
}

function formatMb(n: number) {
  if (!n || n <= 0) return "0 MB";
  if (n >= 1024) return `${(n/1024).toFixed(1)} GB`;
  return `${Math.round(n)} MB`;
}

export default function MenuBar({
  agentPhase,
  modelStatus,
  generationStats,
  workingDirectory,
  onOpenFolder,
  onNewSession,
  onOpenSettings,
}: Props) {
  const handleMinimize = () => { getCurrentWindow().minimize().catch(() => {}); };
  const handleToggleMaximize = async () => {
    const w = getCurrentWindow();
    try {
      const maximized = await w.isMaximized();
      if (maximized) {
        await w.unmaximize();
      } else {
        await w.maximize();
      }
    } catch (e) {
      // ignore
    }
  };
  const handleClose = () => { getCurrentWindow().close().catch(() => {}); };
  return (
    <div
      onMouseDown={handleDragStart}
      style={{
        height: 40,
        background: "#0d000d",
        borderBottom: "1px solid #ff2d9844",
        display: "flex",
        alignItems: "center",
        padding: "0 12px",
        gap: 8,
        userSelect: "none",
        flexShrink: 0,
        cursor: "default",
        // Subtle pink glow on the bottom border
        boxShadow: "0 1px 8px #ff2d9822",
      }}
    >
      {/* App name */}
      <span
        style={{
          color: "#ff2d98",
          fontWeight: 700,
          fontSize: 13,
          marginRight: 8,
          letterSpacing: "0.06em",
          textShadow: "0 0 8px #ff2d9888",
        }}
      >
        CyberPaw
      </span>

      <MenuButton onClick={onOpenFolder} title="Open folder">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ verticalAlign: "middle", marginRight: 5 }}>
          <path d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.379a1.5 1.5 0 0 1 1.06.44l.602.601A1.5 1.5 0 0 0 8.6 3.5H13.5A1.5 1.5 0 0 1 15 5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12V3.5Z"
            stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
        </svg>
        Open
      </MenuButton>

      <MenuButton onClick={onNewSession} title="Start a new session">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ verticalAlign: "middle", marginRight: 5 }}>
          <path d="M13.5 8A5.5 5.5 0 1 1 8 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          <path d="M8 1l2.5 2L8 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        New
      </MenuButton>

      {/* Current workspace indicator */}
      {typeof workingDirectory === "string" && workingDirectory !== "~" && (
        <span
          title={workingDirectory}
          style={{
            fontSize: 11,
            color: "#888888",
            fontFamily: "monospace",
            maxWidth: 200,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            cursor: "default",
            marginLeft: 8,
          }}
        >
          {shortenPath(workingDirectory)}
        </span>
      )}

      <div style={{ flex: 1 }} />

      {/* Phase indicator */}
      <span
        style={{
          fontSize: 11,
          color: PHASE_COLOR[agentPhase],
          fontFamily: "monospace",
          textShadow: `0 0 6px ${PHASE_COLOR[agentPhase]}88`,
        }}
      >
        ● {PHASE_LABEL[agentPhase]}
      </span>

      {/* Model badge */}
      <span
        style={{
          fontSize: 11,
          background: modelStatus.loaded ? "#ff2d9811" : "#1a001a",
          color: modelStatus.loaded ? "#ff2d98" : "#888888",
          border: `1px solid ${modelStatus.loaded ? "#ff2d9866" : "#444444"}`,
          borderRadius: 10,
          padding: "1px 8px",
          fontFamily: "monospace",
          boxShadow: modelStatus.loaded ? "0 0 6px #ff2d9833" : "none",
        }}
        title={`Backend: ${modelStatus.backend}`}
      >
        {modelStatus.loaded ? modelStatus.backend : "no model"}
      </span>

      {/* Memory badge (weights | kv | total) */}
      {modelStatus.loaded && (
        <span
          title={`Detailed breakdown: \n- Weights: ${modelStatus.modelSizeMb} MiB\n- KV Cache: ${modelStatus.kvCacheMb} MiB\n- Total RSS: ${modelStatus.vramUsedMb} MiB`}
          style={{
            fontSize: 11,
            background: "#0a000a",
            color: "#cc88ff",
            border: "1px solid #cc88ff44",
            borderRadius: 10,
            padding: "1px 8px",
            fontFamily: "monospace",
            cursor: "default",
            marginLeft: 8,
            display: "flex",
            gap: 6,
          }}
        >
          <span style={{ opacity: 0.8 }}>W:</span>
          <span>{modelStatus.modelSizeMb > 0 ? formatMb(modelStatus.modelSizeMb) : "..."}</span>
          <span style={{ color: "#cc88ff44" }}>|</span>
          <span style={{ opacity: 0.8 }}>KV:</span>
          <span>{modelStatus.kvCacheMb > 0 ? formatMb(modelStatus.kvCacheMb) : "..."}</span>
          <span style={{ color: "#cc88ff44" }}>|</span>
          <span style={{ opacity: 0.8 }}>Σ</span>
          <span>{modelStatus.vramUsedMb > 0 ? formatMb(modelStatus.vramUsedMb) : "..."}</span>
        </span>
      )}

      {/* Token generation stats badge */}
      <span
        title={
          generationStats.totalTokens > 0
            ? `Tokens generated this session: ${generationStats.totalTokens}\nLast generation speed: ${generationStats.tokensPerSec} tok/s`
            : "No tokens generated yet"
        }
        style={{
          fontSize: 11,
          background: "#000a0a",
          color: generationStats.totalTokens > 0 ? "#44ddcc" : "#444444",
          border: `1px solid ${generationStats.totalTokens > 0 ? "#44ddcc44" : "#333333"}`,
          borderRadius: 10,
          padding: "1px 8px",
          fontFamily: "monospace",
          cursor: "default",
          marginLeft: 8,
          display: "flex",
          gap: 6,
        }}
      >
        <span style={{ opacity: 0.8 }}>tok:</span>
        <span>{generationStats.totalTokens > 0 ? generationStats.totalTokens : "—"}</span>
        <span style={{ color: generationStats.totalTokens > 0 ? "#44ddcc44" : "#333333" }}>|</span>
        <span>{generationStats.tokensPerSec > 0 ? `${generationStats.tokensPerSec} tok/s` : "—"}</span>
      </span>

      <MenuButton onClick={onOpenSettings} title="Settings">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ verticalAlign: "middle" }}>
          <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.4"/>
          <path d="M8 1v1.5M8 13.5V15M15 8h-1.5M2.5 8H1M12.36 3.64l-1.06 1.06M4.7 11.3l-1.06 1.06M12.36 12.36l-1.06-1.06M4.7 4.7 3.64 3.64"
            stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
        </svg>
      </MenuButton>

      <div style={{ width: 4 }} />

      {/* Window Controls */}
      <div style={{ display: "flex", gap: 0 }}>
        <WindowControlButton
          onClick={handleMinimize}
          title="Minimize"
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor">
            <rect x="2" y="8" width="12" height="1.5" rx="0.5" />
          </svg>
        </WindowControlButton>
        <WindowControlButton
          onClick={handleToggleMaximize}
          title="Maximize"
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
            <rect x="3.5" y="3.5" width="9" height="9" stroke="currentColor" strokeWidth="1.4" rx="0.5" />
          </svg>
        </WindowControlButton>
        <WindowControlButton
          onClick={handleClose}
          title="Close"
          hoverColor="#ff4444"
        >
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none">
            <path d="M4 4l8 8M12 4L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </WindowControlButton>
      </div>
    </div>
  );
}

function WindowControlButton({
  children,
  onClick,
  title,
  hoverColor = "#ff2d98",
}: {
  children: React.ReactNode;
  onClick: () => void;
  title?: string;
  hoverColor?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: "transparent",
        border: "none",
        color: "#666666",
        cursor: "pointer",
        padding: "8px 10px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: "color 0.1s, background 0.1s",
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLElement;
        el.style.color = "#ffffff";
        el.style.background = hoverColor === "#ff2d98" ? "#ff2d9822" : `${hoverColor}22`;
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLElement;
        el.style.color = "#666666";
        el.style.background = "transparent";
      }}
    >
      {children}
    </button>
  );
}

function MenuButton({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        background: "transparent",
        border: "1px solid #ff2d9833",
        color: "#aaaaaa",
        fontSize: 11,
        cursor: "pointer",
        padding: "3px 10px",
        borderRadius: 20,
        fontFamily: "inherit",
        letterSpacing: "0.04em",
        display: "inline-flex",
        alignItems: "center",
        transition: "color 0.15s, border-color 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLElement;
        el.style.color = "#ff2d98";
        el.style.borderColor = "#ff2d9888";
        el.style.boxShadow = "0 0 8px #ff2d9844";
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLElement;
        el.style.color = "#aaaaaa";
        el.style.borderColor = "#ff2d9833";
        el.style.boxShadow = "none";
      }}
    >
      {children}
    </button>
  );
}
