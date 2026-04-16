/**
 * ModelLoadProgress — fixed bottom bar shown while a model is loading.
 * Cyberpunk black + pink theme.
 */

import { useEffect, useRef, useState } from "react";

export interface LoadProgress {
  pct: number;
  backend: string;
  heartbeat?: boolean;
  text?: string;
}

interface Props {
  progress: LoadProgress | null;
}

export default function ModelLoadProgress({ progress }: Props) {
  const [visible, setVisible] = useState(false);
  const [displayPct, setDisplayPct] = useState(0);
  const [pulse, setPulse] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!progress) return;

    setVisible(true);
    setDisplayPct(progress.pct);

    if (progress.heartbeat) {
      setPulse(true);
      setTimeout(() => setPulse(false), 400);
    }

    if (progress.pct >= 100) {
      if (hideTimer.current) clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setVisible(false), 1500);
    }

    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [progress]);

  if (!visible || !progress) return null;

  const isDone = displayPct >= 100;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        background: "#0d000d",
        borderTop: "1px solid #ff2d9844",
        boxShadow: "0 -4px 20px #ff2d9818",
        padding: "8px 16px 10px",
        zIndex: 150,
        display: "flex",
        flexDirection: "column",
        gap: 5,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ color: "#ffffff", fontSize: 11 }}>
          {progress.text ? progress.text : (isDone
            ? `✓ ${progress.backend} ready`
            : `Loading ${progress.backend}…`)}
        </span>
        <span
          style={{
            color: isDone ? "#ff2d98" : "#cc00ff",
            fontSize: 11,
            fontWeight: 600,
            fontFamily: "monospace",
            textShadow: isDone ? "0 0 8px #ff2d9888" : "0 0 8px #cc00ff88",
          }}
        >
          {isDone ? "100%" : `${displayPct}%`}
        </span>
      </div>

      <div
        style={{
          height: 4,
          background: "#1a001a",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        {isDone ? (
          <div
            style={{
              height: "100%",
              width: "100%",
              background: "#ff2d98",
              borderRadius: 2,
              boxShadow: "0 0 8px #ff2d98",
            }}
          />
        ) : (
          <div
            style={{
              height: "100%",
              width: `${Math.max(displayPct, 2)}%`,
              background: pulse
                ? "linear-gradient(90deg, #7700cc, #ff2d98, #7700cc)"
                : "linear-gradient(90deg, #7700cc, #ff2d98)",
              borderRadius: 2,
              transition: pulse ? "none" : "width 0.4s ease",
              backgroundSize: pulse ? "200% 100%" : "100% 100%",
              animation: pulse ? "shimmer 0.4s ease" : "none",
              boxShadow: "0 0 6px #ff2d9866",
            }}
          />
        )}
      </div>

      {displayPct === 0 && !isDone && (
        <div
          style={{
            position: "absolute",
            bottom: 10,
            left: 16,
            right: 16,
            height: 4,
            background: "transparent",
            overflow: "hidden",
            borderRadius: 2,
          }}
        >
          <div
            style={{
              height: "100%",
              width: "30%",
              background: "linear-gradient(90deg, transparent, #ff2d98, transparent)",
              animation: "slide 1.5s ease-in-out infinite",
            }}
          />
        </div>
      )}

      <style>{`
        @keyframes shimmer {
          0%   { background-position: 100% 0; }
          100% { background-position: -100% 0; }
        }
        @keyframes slide {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(450%); }
        }
      `}</style>
    </div>
  );
}
