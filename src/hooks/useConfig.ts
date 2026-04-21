/**
 * useConfig — persistent settings
 *
 * Persists to two layers:
 *   1. localStorage — always available, survives restarts in both dev and prod
 *   2. tauri-plugin-store — written as a backup when available
 *
 * On mount, localStorage is read synchronously so config.model_path is set
 * in the very first render, before any async work. This guarantees the
 * auto-load effect in App.tsx fires with the correct value.
 */

import { invoke } from "@tauri-apps/api/core";
import { useCallback, useState } from "react";

export interface AppConfig {
  working_directory: string;
  model_path: string;
  context_size: number;
  max_new_tokens: number;
  auto_context: boolean;
  auto_max_tokens: boolean;
  permission_mode: "ask" | "auto_read" | "auto_all";
  network_enabled: boolean;
}

const DEFAULT_CONFIG: AppConfig = {
  working_directory: "~",
  model_path: "",
  context_size: 0,
  max_new_tokens: 4096,
  auto_context: true,
  auto_max_tokens: true,
  permission_mode: "ask",
  network_enabled: false,
};

const LS_KEY = "cyberpaw_config";

function readLocalStorage(): AppConfig {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {}
  return DEFAULT_CONFIG;
}

function writeLocalStorage(config: AppConfig): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(config));
  } catch {}
}

export function useConfig() {
  // Initialise synchronously from localStorage so the first render already
  // has the persisted model_path — no async gap for the auto-load effect.
  const [config, setConfig] = useState<AppConfig>(readLocalStorage);

  const updateConfig = useCallback((patch: Partial<AppConfig>) => {
    const next: AppConfig = { ...config, ...patch };
    setConfig(next);
    writeLocalStorage(next);
    invoke("set_config", { config: next }).catch(() => {});
  }, [config]);

  return { config, updateConfig };
}
