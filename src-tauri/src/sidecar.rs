use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Global handle to the sidecar child process stdin writer.
pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
}

pub fn spawn_sidecar(app: AppHandle) -> anyhow::Result<()> {
    let sidecar_cmd = app
        .shell()
        .sidecar("snowpaw-agent")
        .map_err(|e| anyhow::anyhow!("sidecar not found: {e}"))?;

    let (mut rx, child) = sidecar_cmd.spawn()?;

    // Store child in managed state so commands can write to stdin
    app.manage(SidecarState {
        child: Mutex::new(Some(child)),
    });

    let app_clone = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    // Each line is a JSON object — forward as agent://stream event
                    if let Ok(text) = String::from_utf8(line) {
                        let trimmed = text.trim();
                        if !trimmed.is_empty() {
                            let _ = app_clone.emit("agent://stream", trimmed);
                        }
                    }
                }
                CommandEvent::Stderr(line) => {
                    if let Ok(text) = String::from_utf8(line) {
                        let trimmed = text.trim();
                        if !trimmed.is_empty() {
                            let payload = serde_json::json!({
                                "type": "stderr",
                                "text": trimmed
                            });
                            let _ = app_clone.emit("agent://stream", payload.to_string());
                        }
                    }
                }
                CommandEvent::Terminated(status) => {
                    let payload = serde_json::json!({
                        "type": "sidecar_exit",
                        "code": status.code
                    });
                    let _ = app_clone.emit("agent://stream", payload.to_string());
                    // Clear the child handle
                    if let Some(state) = app_clone.try_state::<SidecarState>() {
                        let mut lock = state.child.lock().unwrap();
                        *lock = None;
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Write a JSON line to the sidecar's stdin.
pub fn write_to_sidecar(app: &AppHandle, payload: serde_json::Value) -> anyhow::Result<()> {
    let state = app
        .state::<SidecarState>();
    let mut lock = state.child.lock().unwrap();
    if let Some(child) = lock.as_mut() {
        let mut line = payload.to_string();
        line.push('\n');
        child.write(line.as_bytes())?;
        Ok(())
    } else {
        Err(anyhow::anyhow!("sidecar not running"))
    }
}
