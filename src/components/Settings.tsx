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
  onLoadModel: (modelPath: string, backend?: string) => void;
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
}: Props) {
  const [draft, setDraft] = useState<AppConfig>({ ...config });
  const [showDownloader, setShowDownloader] = useState(!config.model_path);

  const set = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const pickModelPath = async () => {
    const selected = await openDialog({
      multiple: false,
      filters: [{ name: "Model", extensions: ["gguf", "bin", "safetensors"] }],
    });
    if (typeof selected === "string") set("model_path", selected);
  };

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

        {/* Model Path */}
        <Field label="Model Path (.gguf or HF dir)">
          <div style={{ display: "flex", gap: 6 }}>
            <input
              value={draft.model_path}
              onChange={(e) => set("model_path", e.target.value)}
              placeholder="e.g. ~/models/gemma-4-e4b.gguf"
              style={inputStyle}
            />
            <button onClick={pickModelPath} style={btnStyle}>Browse</button>
          </div>
          <button
            onClick={() => setShowDownloader((v) => !v)}
            style={{
              ...btnStyle,
              marginTop: 4,
              color: "#cc00ff",
              borderColor: "#cc00ff44",
              fontSize: 11,
            }}
          >
            {showDownloader ? "▲ Hide downloader" : "▼ Download a model…"}
          </button>
        </Field>

        {showDownloader && (
          <ModelDownloader
            catalog={modelCatalog}
            progress={downloadProgress}
            downloadedPath={downloadedModelPath}
            onFetchCatalog={onFetchCatalog}
            onStart={onStartDownload}
            onCancel={onCancelDownload}
            onUseModel={(path) => {
              set("model_path", path);
              setShowDownloader(false);
              onLoadModel(path, draft.backend);
            }}
          />
        )}

        {/* Backend */}
        <Field label="LLM Backend">
          <RadioGroup
            options={[
              { value: "auto", label: "Auto (detect memory)" },
              { value: "llamacpp", label: "llama.cpp (GGUF, faster)" },
              { value: "airllm", label: "AirLLM (low memory)" },
            ]}
            value={draft.backend}
            onChange={(v) => set("backend", v as AppConfig["backend"])}
          />
        </Field>

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

        {/* Context Size */}
        <Field label={`Context Window: ${draft.context_size} tokens`}>
          <input
            type="range"
            min={2048}
            max={32768}
            step={1024}
            value={draft.context_size}
            onChange={(e) => set("context_size", Number(e.target.value))}
            style={{ width: "100%", accentColor: "#ff2d98" }}
          />
        </Field>

        {/* Max New Tokens */}
        <Field label="Max New Tokens">
          <input
            type="number"
            min={256}
            max={8192}
            value={draft.max_new_tokens}
            onChange={(e) => set("max_new_tokens", Number(e.target.value))}
            style={{ ...inputStyle, width: 100 }}
          />
        </Field>

        {/* Temperature */}
        <Field label={`Temperature: ${draft.temperature.toFixed(2)}`}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={draft.temperature}
            onChange={(e) => set("temperature", Number(e.target.value))}
            style={{ width: "100%", accentColor: "#ff2d98" }}
          />
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
              Allow network access (WebFetch, WebSearch)
            </span>
          </label>
          <span style={{ color: "#ff2d98", fontSize: 11 }}>
            Off by default. Network calls still require permission approval in Ask mode.
          </span>
        </Field>

        {/* System Prompt Append */}
        <Field label="Additional System Prompt">
          <textarea
            value={draft.system_prompt_append}
            onChange={(e) => set("system_prompt_append", e.target.value)}
            placeholder="Appended to the default system prompt…"
            rows={4}
            style={{ ...inputStyle, resize: "vertical", fontFamily: "monospace" }}
          />
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
