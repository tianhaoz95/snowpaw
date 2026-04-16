/**
 * MenuBar — top navigation bar (40px)
 * Cyberpunk black + pink theme.
 */

import { getCurrentWindow } from "@tauri-apps/api/window";
import type { AgentPhase, ModelStatus } from "../hooks/useAgent";

interface Props {
  agentPhase: AgentPhase;
  modelStatus: ModelStatus;
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

export default function MenuBar({
  agentPhase,
  modelStatus,
  onOpenFolder,
  onNewSession,
  onOpenSettings,
}: Props) {
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

      <MenuButton onClick={onOpenSettings} title="Settings">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" style={{ verticalAlign: "middle" }}>
          <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.4"/>
          <path d="M8 1v1.5M8 13.5V15M15 8h-1.5M2.5 8H1M12.36 3.64l-1.06 1.06M4.7 11.3l-1.06 1.06M12.36 12.36l-1.06-1.06M4.7 4.7 3.64 3.64"
            stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
        </svg>
      </MenuButton>
    </div>
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
