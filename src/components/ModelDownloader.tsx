/**
 * ModelDownloader — embedded model download UI
 * Cyberpunk black + pink theme.
 */

import { useEffect, useState } from "react";
import type { DownloadProgress, ModelCatalogEntry } from "../hooks/useAgent";

interface Props {
  catalog: ModelCatalogEntry[];
  progress: DownloadProgress | null;
  downloadedPath: string | null;
  onFetchCatalog: () => void;
  onStart: (modelId: string, destDir?: string, hfToken?: string) => void;
  onCancel: () => void;
  onUseModel: (path: string) => void;
}

export default function ModelDownloader({
  catalog,
  progress,
  downloadedPath,
  onFetchCatalog,
  onStart,
  onCancel,
  onUseModel,
}: Props) {
  const [selected, setSelected] = useState<string>("");
  const [destDir, setDestDir] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (catalog.length === 0) onFetchCatalog();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (catalog.length > 0 && !selected) setSelected(catalog[0].id);
  }, [catalog, selected]);

  const isDownloading = progress !== null;
  const selectedEntry = catalog.find((m) => m.id === selected);

  return (
    <div
      style={{
        background: "#080008",
        border: "1px solid #ff2d9833",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div
        style={{
          color: "#ff2d98",
          fontWeight: 600,
          fontSize: 13,
          letterSpacing: "0.04em",
          textShadow: "0 0 8px #ff2d9866",
        }}
      >
        Download a Model
      </div>

      {catalog.length === 0 ? (
        <div style={{ color: "#ff2d98", fontSize: 12 }}>
          Loading catalog…{" "}
          <button onClick={onFetchCatalog} style={linkBtnStyle}>
            retry
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {catalog.map((m) => (
            <label
              key={m.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                cursor: "pointer",
                padding: "8px 10px",
                borderRadius: 6,
                border: `1px solid ${selected === m.id ? "#ff2d9866" : "#2a002a"}`,
                background: selected === m.id ? "#ff2d9811" : "transparent",
                boxShadow: selected === m.id ? "0 0 8px #ff2d9822" : "none",
                transition: "all 0.15s",
              }}
            >
              <input
                type="radio"
                value={m.id}
                checked={selected === m.id}
                onChange={() => setSelected(m.id)}
                style={{ marginTop: 2, flexShrink: 0, accentColor: "#ff2d98" }}
                disabled={isDownloading}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: "#ffffff", fontSize: 13, fontWeight: 500 }}>
                  {m.name}
                </div>
                <div style={{ color: "#ffffff", fontSize: 11, marginTop: 2 }}>
                  {m.description}
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                  <Tag>{m.quant}</Tag>
                  <Tag>{m.size_gb} GB</Tag>
                  {m.requires_hf_token && <Tag color="#ff2d98">HF token required</Tag>}
                </div>
              </div>
            </label>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <label style={{ color: "#ffffff", fontSize: 11 }}>
          Save to (leave blank for ~/models/cyberpaw/)
        </label>
        <input
          value={destDir}
          onChange={(e) => setDestDir(e.target.value)}
          placeholder="~/models/cyberpaw"
          disabled={isDownloading}
          style={inputStyle}
        />
      </div>

      {selectedEntry?.requires_hf_token && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ color: "#ffffff", fontSize: 11 }}>
            HuggingFace token
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type={showToken ? "text" : "password"}
              value={hfToken}
              onChange={(e) => setHfToken(e.target.value)}
              placeholder="hf_…"
              disabled={isDownloading}
              style={{ ...inputStyle, flex: 1 }}
            />
            <button onClick={() => setShowToken((v) => !v)} style={smallBtnStyle}>
              {showToken ? "Hide" : "Show"}
            </button>
          </div>
        </div>
      )}

      {isDownloading && progress && <ProgressBar progress={progress} />}

      {downloadedPath && !isDownloading && (
        <div
          style={{
            background: "#ff2d9811",
            border: "1px solid #ff2d9866",
            borderRadius: 6,
            padding: "8px 12px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            boxShadow: "0 0 10px #ff2d9833",
          }}
        >
          <span style={{ color: "#ff2d98", fontSize: 12, textShadow: "0 0 6px #ff2d9866" }}>
            ✓ Downloaded successfully
          </span>
          <button
            onClick={() => onUseModel(downloadedPath)}
            style={{
              ...smallBtnStyle,
              background: "#ff2d9822",
              borderColor: "#ff2d98",
              color: "#ff2d98",
              fontWeight: 600,
            }}
          >
            Use this model
          </button>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        {isDownloading ? (
          <button onClick={onCancel} style={dangerBtnStyle}>
            Cancel download
          </button>
        ) : (
          <button
            onClick={() =>
              selected && onStart(selected, destDir || undefined, hfToken || undefined)
            }
            disabled={!selected || catalog.length === 0}
            style={{
              ...primaryBtnStyle,
              opacity: !selected || catalog.length === 0 ? 0.4 : 1,
              cursor: !selected || catalog.length === 0 ? "not-allowed" : "pointer",
            }}
          >
            Download
          </button>
        )}
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ProgressBar({ progress }: { progress: DownloadProgress }) {
  const { pct, downloadedMb, totalMb, speedMbps, resuming } = progress;
  const label = totalMb
    ? `${downloadedMb} / ${totalMb} MB`
    : `${downloadedMb} MB`;
  const speed = speedMbps > 0 ? ` · ${speedMbps} MB/s` : "";
  const eta =
    speedMbps > 0 && totalMb
      ? ` · ~${Math.ceil((totalMb - downloadedMb) / speedMbps)}s left`
      : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ color: "#ffffff", fontSize: 11 }}>
          {resuming ? "Resuming… " : "Downloading… "}
          {label}{speed}{eta}
        </span>
        <span
          style={{
            color: "#ff2d98",
            fontSize: 11,
            fontWeight: 600,
            textShadow: "0 0 6px #ff2d9888",
          }}
        >
          {pct}%
        </span>
      </div>
      <div
        style={{
          height: 6,
          background: "#1a001a",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "linear-gradient(90deg, #7700cc, #ff2d98)",
            borderRadius: 3,
            transition: "width 0.25s ease",
            boxShadow: "0 0 6px #ff2d9866",
          }}
        />
      </div>
    </div>
  );
}

function Tag({
  children,
  color = "#ff2d98",
}: {
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <span
      style={{
        background: color + "22",
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: "1px 5px",
        fontSize: 10,
        color: color === "#ff2d98" ? "#ffffff" : color,
        fontFamily: "monospace",
      }}
    >
      {children}
    </span>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  background: "#0d000d",
  border: "1px solid #ff2d9833",
  borderRadius: 6,
  color: "#ffffff",
  padding: "5px 8px",
  fontSize: 12,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
  fontFamily: "monospace",
};

const smallBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ff2d98",
  borderRadius: 6,
  color: "#ffffff",
  padding: "4px 10px",
  fontSize: 12,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const primaryBtnStyle: React.CSSProperties = {
  background: "#ff2d9822",
  border: "1px solid #ff2d98",
  borderRadius: 6,
  color: "#ff2d98",
  padding: "5px 16px",
  fontSize: 13,
  cursor: "pointer",
  fontWeight: 600,
  boxShadow: "0 0 8px #ff2d9844",
};

const dangerBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid #ff5555",
  borderRadius: 6,
  color: "#ff5555",
  padding: "5px 16px",
  fontSize: 13,
  cursor: "pointer",
};

const linkBtnStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  color: "#cc00ff",
  fontSize: 12,
  cursor: "pointer",
  padding: 0,
  textDecoration: "underline",
};
