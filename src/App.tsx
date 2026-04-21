import { useEffect, useRef, useState } from "react";
import MenuBar from "./components/MenuBar";
import Terminal from "./components/Terminal";
import Settings from "./components/Settings";
import PermissionDialog from "./components/PermissionDialog";
import ModelLoadProgress from "./components/ModelLoadProgress";
import { useAgent } from "./hooks/useAgent";
import { useConfig } from "./hooks/useConfig";

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { config, updateConfig } = useConfig();
  const {
    sendInput,
    interrupt,
    resetSession,
    setWorkingDirectory,
    pendingPermission,
    resolvePermission,
    modelStatus,
    generationStats,
    agentPhase,
    turnState,
    writeToTerminal,
    writeTerminal,
    loadModel,
    loadProgress,
    fetchCatalog,
    startDownload,
    cancelDownload,
    downloadProgress,
    downloadedModelPath,
    modelCatalog,
  } = useAgent();

  const autoLoadedRef = useRef(false);
  const spinnerTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clear the spinner as soon as the model reports loaded.
  useEffect(() => {
    if (modelStatus.loaded) {
      if (spinnerTimerRef.current !== null) {
        clearInterval(spinnerTimerRef.current);
        spinnerTimerRef.current = null;
        // \x1b[2K clears the line, \r moves to the start.
        writeTerminal("\x1b[2K\r\x1b[38;2;255;45;152mModel ready.\x1b[0m\r\n\x1b[38;2;255;45;152m❯\x1b[0m ");
      }
    }
  }, [modelStatus.loaded, writeTerminal]);
  useEffect(() => {
    if (autoLoadedRef.current) return;
    autoLoadedRef.current = true;

    // Small delay so Terminal has mounted and writeToTerminal.current is set.
    setTimeout(() => {
      // Restore last-used workspace before loading the model
      if (config.working_directory && config.working_directory !== "~") {
        setWorkingDirectory(config.working_directory);
      }

      if (config.model_path) {
        const frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
        let i = 0;
        const P = "\x1b[38;2;255;45;152m";
        const R = "\x1b[0m";
        const modelName = config.model_path.split(/[/\\]/).pop();
        
        // Initial line — NO newline, the spinner will stay on this line via \r
        writeTerminal(`${P}${frames[0]}${R} Loading ${modelName}…`);
        spinnerTimerRef.current = setInterval(() => {
          i = (i + 1) % frames.length;
          // \r moves to start of line, rewrite in place
          writeTerminal(`\r${P}${frames[i]}${R} Loading ${modelName}…`);
        }, 80);
        loadModel(config.model_path);
      } else {
        writeTerminal(
          "\x1b[2mNo model loaded — open Settings to load one.\x1b[0m\r\n"
          + "\x1b[38;2;255;45;152m❯\x1b[0m "
        );
      }
    }, 50);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app">
      <MenuBar
        agentPhase={agentPhase}
        turnState={turnState}
        modelStatus={modelStatus}
        generationStats={generationStats}
        onOpenFolder={async () => {
          const { open } = await import("@tauri-apps/plugin-dialog");
          const selected = await open({ directory: true, multiple: false });
          if (typeof selected === "string") {
            setWorkingDirectory(selected);
            updateConfig({ working_directory: selected });
          }
        }}
        onNewSession={resetSession}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <Terminal
        onInput={sendInput}
        onInterrupt={interrupt}
        modelLoaded={modelStatus.loaded}
        writeToTerminalRef={writeToTerminal}
      />

      {settingsOpen && (
        <Settings
          config={config}
          onSave={(patch) => {
            updateConfig(patch);
            // If model_path changed, trigger a load immediately
            if (patch.model_path && patch.model_path !== config.model_path) {
              loadModel(patch.model_path);
            }
            setSettingsOpen(false);
          }}
          onClose={() => setSettingsOpen(false)}
          modelCatalog={modelCatalog}
          downloadProgress={downloadProgress}
          downloadedModelPath={downloadedModelPath}
          onFetchCatalog={fetchCatalog}
          onStartDownload={startDownload}
          onCancelDownload={cancelDownload}
          onLoadModel={(path) => {
            updateConfig({ model_path: path });
            loadModel(path);
          }}
        />
      )}

      {pendingPermission && (
        <PermissionDialog
          permission={pendingPermission}
          onResolve={resolvePermission}
        />
      )}

      <ModelLoadProgress progress={loadProgress} />
    </div>
  );
}
