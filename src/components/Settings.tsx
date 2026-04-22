/**
 * Settings — slide-in configuration panel
 * Cyberpunk black + pink theme.
 */

import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { useState } from "react";
import type { DownloadProgress, ModelCatalogEntry } from "../hooks/useAgent";
import type { AppConfig } from "../hooks/useConfig";
import ModelDownloader from "./ModelDownloader";

interface Props {
  config: AppConfig;
  onSave: (patch: Partial<AppConfig>) => void;
  onClose: () => void;
  modelCatalog: ModelCatalogEntry[];
  downloadProgress: DownloadProgress | null;
  downloadedModelPath: string | null;
  onFetchCatalog: () => void;
  onStartDownload: (modelId: string, destDir?: string, hfToken?: string) => void;
  onCancelDownload: () => void;
  onLoadModel: (modelPath: string) => void;
  onCheckInstalled: (dir: string) => Promise<Set<string>>;
}

export default function Settings({
  config,
  onSave,
  onClose,
  modelCatalog,
  downloadProgress,
  downloadedModelPath,
  onFetchCatalog,
  onStartDownload,
  onCancelDownload,
  onLoadModel,
  onCheckInstalled,
}: Props) {
  const [draft, setDraft] = useState<AppConfig>({ ...config });

  const set = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const pickWorkingDir = async () => {
    const selected = await openDialog({ directory: true, multiple: false });
    if (typeof selected === "string") set("working_directory", selected);
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "#08000888",
        display: "flex",
        justifyContent: "flex-end",
        zIndex: 100,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        style={{
          width: 380,
          background: "#0d000d",
          borderLeft: "1px solid #ff2d9844",
          boxShadow: "-4px 0 32px #ff2d9818",
          padding: 24,
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2
            style={{
              color: "#ff2d98",
              margin: 0,
              fontSize: 16,
              fontWeight: 700,
              letterSpacing: "0.06em",
              textShadow: "0 0 10px #ff2d9866",
            }}
          >
            Settings
          </h2>
          <button onClick={onClose} style={iconBtnStyle}>✕</button>
        </div>

        {/* Working Directory */}
        <Field label="Working Directory">
          <div style={{ display: "flex", gap: 6 }}>
            <input
              value={draft.working_directory}
              onChange={(e) => set("working_directory", e.target.value)}
              style={inputStyle}
            />
            <button onClick={pickWorkingDir} style={btnStyle}>Browse</button>
          </div>
        </Field>

        {/* Active model */}
        {draft.model_path && (
          <Field label="Active Model">
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ ...inputStyle, flex: 1, color: "#aaa", fontSize: 11, fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {draft.model_path.split(/[/\\]/).pop()}
              </span>
              <button
                onClick={() => set("model_path", "")}
                style={{ ...btnStyle, borderColor: "#ff5555", color: "#ff5555" }}
              >
                Clear
              </button>
            </div>
          </Field>
        )}

        <ModelDownloader
          catalog={modelCatalog}
          progress={downloadProgress}
          downloadedPath={downloadedModelPath}
          onFetchCatalog={onFetchCatalog}
          onStart={onStartDownload}
          onCancel={onCancelDownload}
          onCheckInstalled={onCheckInstalled}
          onUseModel={(path) => {
            set("model_path", path);
            onLoadModel(path);
            onClose();
          }}
        />

        {/* Permission Mode */}
        <Field label="Permission Mode">
          <RadioGroup
            options={[
              { value: "ask", label: "Ask (prompt for writes/bash)" },
              { value: "auto_read", label: "Auto-approve reads" },
              { value: "auto_all", label: "Auto-approve all (caution)" },
            ]}
            value={draft.permission_mode}
            onChange={(v) => set("permission_mode", v as AppConfig["permission_mode"])}
          />
        </Field>

        {/* Context Window */}
        <Field label="Context Window">
          <Toggle
            checked={draft.auto_context}
            onChange={(v) => set("auto_context", v)}
            label={draft.auto_context
              ? `Auto${draft.context_size ? ` — ${draft.context_size.toLocaleString()} tokens` : ""}`
              : `Manual — ${draft.context_size.toLocaleString()} tokens`}
          />
          {!draft.auto_context && (
            <input
              type="range"
              min={4096}
              max={131072}
              step={4096}
              value={draft.context_size || 32768}
              onChange={(e) => set("context_size", Number(e.target.value))}
              style={{ width: "100%", accentColor: "#ff2d98", marginTop: 6 }}
            />
          )}
          {!draft.auto_context && (
            <span style={{ color: "#888", fontSize: 11 }}>
              Requires model reload to take effect.
            </span>
          )}
        </Field>

        {/* Max New Tokens */}
        <Field label="Max New Tokens">
          <Toggle
            checked={draft.auto_max_tokens}
            onChange={(v) => set("auto_max_tokens", v)}
            label={draft.auto_max_tokens
              ? `Auto — ${draft.max_new_tokens.toLocaleString()} tokens`
              : `Manual — ${draft.max_new_tokens.toLocaleString()} tokens`}
          />
          {!draft.auto_max_tokens && (
            <input
              type="range"
              min={256}
              max={8192}
              step={256}
              value={draft.max_new_tokens}
              onChange={(e) => set("max_new_tokens", Number(e.target.value))}
              style={{ width: "100%", accentColor: "#ff2d98", marginTop: 6 }}
            />
          )}
        </Field>



        {/* Network Access */}
        <Field label="Network Access">
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={draft.network_enabled}
              onChange={(e) => set("network_enabled", e.target.checked)}
              style={{ accentColor: "#ff2d98" }}
            />
            <span style={{ color: "#ffffff", fontSize: 13 }}>
              Allow network access (WebFetch, WebSearch, Playwright)
            </span>
          </label>
          <span style={{ color: "#ff2d98", fontSize: 11 }}>
            Off by default. Network calls still require permission approval in Ask mode.
          </span>
        </Field>



        {/* Save / Cancel */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btnStyle}>Cancel</button>
          <button
            onClick={() => onSave(draft)}
            style={{
              ...btnStyle,
              background: "#ff2d9822",
              color: "#ff2d98",
              borderColor: "#ff2d98",
              boxShadow: "0 0 10px #ff2d9844",
              fontWeight: 600,
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}>
      <div
        onClick={() => onChange(!checked)}
        style={{
          width: 36,
          height: 20,
          borderRadius: 10,
          background: checked ? "#ff2d98" : "#333",
          position: "relative",
          flexShrink: 0,
          transition: "background 0.15s",
          boxShadow: checked ? "0 0 8px #ff2d9866" : "none",
        }}
      >
        <div style={{
          position: "absolute",
          top: 2,
          left: checked ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          transition: "left 0.15s",
        }} />
      </div>
      <span style={{ color: "#ccc", fontSize: 13 }}>{label}</span>
    </label>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ color: "#ffffff", fontSize: 12, letterSpacing: "0.04em" }}>{label}</label>
      {children}
    </div>
  );
}

function RadioGroup({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {options.map((opt) => (
        <label
          key={opt.value}
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <input
            type="radio"
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            style={{ accentColor: "#ff2d98" }}
          />
          <span style={{ color: "#ffffff", fontSize: 13 }}>{opt.label}</span>
        </label>
      ))}
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  flex: 1,
  background: "#080008",
  border: "1px solid #ff2d9833",
  borderRadius: 6,
  color: "#ffffff",
  padding: "5px 8px",
  fontSize: 13,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const btnStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ff2d98",
  borderRadius: 6,
  color: "#ffffff",
  padding: "4px 12px",
  fontSize: 12,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const iconBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  color: "#ffffff",
  fontSize: 16,
  cursor: "pointer",
  padding: 4,
};
