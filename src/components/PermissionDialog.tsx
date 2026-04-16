/**
 * PermissionDialog — inline tool approval prompt
 * Cyberpunk black + pink theme.
 */

import type { PendingPermission } from "../hooks/useAgent";

interface Props {
  permission: PendingPermission;
  onResolve: (id: string, approved: boolean) => void;
}

export default function PermissionDialog({ permission, onResolve }: Props) {
  const inputStr = JSON.stringify(permission.input, null, 2);
  const truncated =
    inputStr.length > 400 ? inputStr.slice(0, 400) + "\n  …" : inputStr;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        background: "#0d000d",
        borderTop: "1px solid #ff2d9866",
        boxShadow: "0 -4px 24px #ff2d9822",
        padding: "12px 16px",
        zIndex: 200,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "#ff2d98", fontSize: 14, textShadow: "0 0 8px #ff2d98" }}>⚠</span>
        <span style={{ color: "#ffffff", fontWeight: 600, fontSize: 13 }}>
          Allow{" "}
          <code
            style={{
              color: "#ff2d98",
              background: "#ff2d9811",
              border: "1px solid #ff2d9844",
              borderRadius: 4,
              padding: "0 4px",
              textShadow: "0 0 6px #ff2d9866",
            }}
          >
            {permission.tool}
          </code>
          ?
        </span>
      </div>

      <pre
        style={{
          background: "#080008",
          border: "1px solid #ff2d9833",
          borderRadius: 6,
          padding: "8px 10px",
          fontSize: 12,
          color: "#ffffff",
          margin: 0,
          overflowX: "auto",
          maxHeight: 160,
          overflowY: "auto",
          fontFamily: "monospace",
        }}
      >
        {truncated}
      </pre>

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => onResolve(permission.id, true)}
          style={{
            background: "#ff2d9822",
            border: "1px solid #ff2d98",
            borderRadius: 6,
            color: "#ff2d98",
            padding: "5px 20px",
            fontSize: 13,
            cursor: "pointer",
            fontWeight: 600,
            boxShadow: "0 0 8px #ff2d9844",
            textShadow: "0 0 6px #ff2d9888",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = "#ff2d9844";
            (e.currentTarget as HTMLElement).style.boxShadow = "0 0 14px #ff2d9866";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "#ff2d9822";
            (e.currentTarget as HTMLElement).style.boxShadow = "0 0 8px #ff2d9844";
          }}
        >
          Allow
        </button>
        <button
          onClick={() => onResolve(permission.id, false)}
          style={{
            background: "transparent",
            border: "1px solid #ff2d98",
            borderRadius: 6,
            color: "#ffffff",
            padding: "5px 20px",
            fontSize: 13,
            cursor: "pointer",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.color = "#ffffff";
            (e.currentTarget as HTMLElement).style.borderColor = "#ffffff";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.color = "#ffffff";
            (e.currentTarget as HTMLElement).style.borderColor = "#ff2d98";
          }}
        >
          Deny
        </button>
        <span style={{ color: "#ff2d98", fontSize: 11, alignSelf: "center" }}>
          (auto-deny in 5 min)
        </span>
      </div>
    </div>
  );
}
