/**
 * ModelDownloader — embedded model download UI
 * Cyberpunk black + pink theme.
 */

import { useEffect, useRef, useState } from "react";
import type { DownloadProgress, ModelCatalogEntry } from "../hooks/useAgent";

const DEFAULT_DEST = "~/CyberPaw/models";

interface Props {
  catalog: ModelCatalogEntry[];
  progress: DownloadProgress | null;
  downloadedPath: string | null;
  onFetchCatalog: () => void;
  onStart: (modelId: string, destDir?: string, hfToken?: string) => void;
  onCancel: () => void;
  onUseModel: (path: string) => void;
  onCheckInstalled: (dir: string) => Promise<Set<string>>;
}

export default function ModelDownloader({
  catalog,
  progress,
  downloadedPath,
  onFetchCatalog,
  onStart,
  onCancel,
  onUseModel,
  onCheckInstalled,
}: Props) {
  const [selected, setSelected] = useState<string>("");
  const [destDir, setDestDir] = useState("");
  const [hfToken, setHfToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [installedFilenames, setInstalledFilenames] = useState<Set<string>>(new Set());
  const scanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (catalog.length === 0) onFetchCatalog();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (catalog.length > 0 && !selected) setSelected(catalog[0].id);
  }, [catalog, selected]);

  // Scan the destination directory for already-downloaded model files.
  const scanInstalled = (dir: string) => {
    const resolved = dir.trim() || DEFAULT_DEST;
    const expand = resolved.startsWith("~")
      ? import("@tauri-apps/api/path").then(({ homeDir }) => homeDir()).then((home) => resolved.replace("~", home))
      : Promise.resolve(resolved);
    expand.then((expanded) => onCheckInstalled(expanded)).then(setInstalledFilenames);
  };

  // Scan on mount and whenever destDir changes (debounced).
  useEffect(() => {
    scanInstalled(destDir);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (scanTimerRef.current) clearTimeout(scanTimerRef.current);
    scanTimerRef.current = setTimeout(() => scanInstalled(destDir), 300);
    return () => {
      if (scanTimerRef.current) clearTimeout(scanTimerRef.current);
    };
  }, [destDir]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-scan after a download completes so the row flips to "Installed".
  useEffect(() => {
    if (downloadedPath) scanInstalled(destDir);
  }, [downloadedPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const isDownloading = progress !== null;
  const selectedEntry = catalog.find((m) => m.id === selected);

  const resolvedPath = (entry: ModelCatalogEntry) => {
    const dir = (destDir.trim() || DEFAULT_DEST).replace(/\/$/, "");
    return `${dir}/${entry.filename}`;
  };

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
        Models
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
          {catalog.map((m) => {
            const installed = installedFilenames.has(m.filename);
            const isSelected = selected === m.id;
            return (
              <label
                key={m.id}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  cursor: "pointer",
                  padding: "8px 10px",
                  borderRadius: 6,
                  border: `1px solid ${isSelected ? (installed ? "#00ff9966" : "#ff2d9866") : "#2a002a"}`,
                  background: isSelected ? (installed ? "#00ff9911" : "#ff2d9811") : "transparent",
                  boxShadow: isSelected ? `0 0 8px ${installed ? "#00ff9922" : "#ff2d9822"}` : "none",
                  transition: "all 0.15s",
                }}
              >
                <input
                  type="radio"
                  value={m.id}
                  checked={isSelected}
                  onChange={() => setSelected(m.id)}
                  style={{ marginTop: 2, flexShrink: 0, accentColor: installed ? "#00ff99" : "#ff2d98" }}
                  disabled={isDownloading}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: "#ffffff", fontSize: 13, fontWeight: 500 }}>
                    {m.name}
                  </div>
                  <div style={{ color: "#aaaaaa", fontSize: 11, marginTop: 2 }}>
                    {m.description}
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                    <Tag>{m.quant}</Tag>
                    <Tag>{m.size_gb} GB</Tag>
                    {m.requires_hf_token && <Tag color="#ff2d98">HF token required</Tag>}
                    {installed && <Tag color="#00ff99">✓ Installed</Tag>}
                  </div>
                </div>
                {installed && (
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      onUseModel(resolvedPath(m));
                    }}
                    disabled={isDownloading}
                    style={{
                      ...smallBtnStyle,
                      alignSelf: "center",
                      borderColor: "#00ff99",
                      color: "#00ff99",
                      opacity: isDownloading ? 0.4 : 1,
                    }}
                  >
                    Load
                  </button>
                )}
              </label>
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <label style={{ color: "#ffffff", fontSize: 11 }}>
          Save to (leave blank for {DEFAULT_DEST}/)
        </label>
        <input
          value={destDir}
          onChange={(e) => setDestDir(e.target.value)}
          placeholder={DEFAULT_DEST}
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
            disabled={!selected || catalog.length === 0 || (selectedEntry != null && installedFilenames.has(selectedEntry.filename))}
            style={{
              ...primaryBtnStyle,
              opacity: (!selected || catalog.length === 0 || (selectedEntry != null && installedFilenames.has(selectedEntry.filename))) ? 0.4 : 1,
              cursor: (!selected || catalog.length === 0 || (selectedEntry != null && installedFilenames.has(selectedEntry.filename))) ? "not-allowed" : "pointer",
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
