use serde::{Deserialize, Serialize};
use tauri::AppHandle;

use crate::sidecar::write_to_sidecar;

// ── Config types ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub working_directory: String,
    pub model_path: String,
    pub context_size: u32,
    pub max_new_tokens: u32,
    pub permission_mode: String, // "ask" | "auto_read" | "auto_all"

    pub network_enabled: bool,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            working_directory: dirs::home_dir()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned(),
            model_path: String::new(),
            context_size: 0,
            max_new_tokens: 4096,
            permission_mode: "ask".into(),
            network_enabled: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelStatus {
    pub backend: String,
    pub loaded: bool,
    pub vram_used_mb: u64,
}

// ── Tauri commands ────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn send_input(app: AppHandle, text: String) -> Result<(), String> {
    let payload = serde_json::json!({"type": "input", "text": text});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_working_directory(app: AppHandle, path: String) -> Result<(), String> {
    let payload = serde_json::json!({"type": "cd", "path": path});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn run_shell_command(app: AppHandle, command: String) -> Result<(), String> {
    let payload = serde_json::json!({"type": "shell", "command": command});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn interrupt_agent(app: AppHandle) -> Result<(), String> {
    let payload = serde_json::json!({"type": "interrupt"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn send_tool_ack(
    app: AppHandle,
    id: String,
    decision: String,
) -> Result<(), String> {
    let payload = serde_json::json!({"type": "tool_ack", "id": id, "decision": decision});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn reset_session(app: AppHandle) -> Result<(), String> {
    let payload = serde_json::json!({"type": "reset"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_model_status(app: AppHandle) -> Result<ModelStatus, String> {
    let payload = serde_json::json!({"type": "status_request"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())?;
    // Status is returned asynchronously via agent://stream event.
    // Return a placeholder; the frontend subscribes to model://progress events.
    Ok(ModelStatus {
        backend: "unknown".into(),
        loaded: false,
        vram_used_mb: 0,
    })
}

#[tauri::command]
pub async fn get_config() -> Result<AppConfig, String> {
    Ok(AppConfig::default())
}

#[tauri::command]
pub async fn set_config(app: AppHandle, config: AppConfig) -> Result<(), String> {
    let payload = serde_json::json!({"type": "config", "patch": config});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn load_model(
    app: AppHandle,
    model_path: String,
    backend: Option<String>,
) -> Result<(), String> {
    let payload = serde_json::json!({
        "type": "load_model",
        "model_path": model_path,
        "backend": backend.unwrap_or_default(),
    });
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_download_catalog(app: AppHandle) -> Result<(), String> {
    let payload = serde_json::json!({"type": "download_catalog"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn start_model_download(
    app: AppHandle,
    model_id: String,
    dest_dir: Option<String>,
    hf_token: Option<String>,
) -> Result<(), String> {
    let payload = serde_json::json!({
        "type": "download_start",
        "model_id": model_id,
        "dest_dir": dest_dir,
        "hf_token": hf_token.unwrap_or_default(),
    });
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn cancel_model_download(app: AppHandle) -> Result<(), String> {
    let payload = serde_json::json!({"type": "download_cancel"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn install_browser(app: AppHandle) -> Result<(), String> {
    let payload = serde_json::json!({"type": "install_browsers"});
    write_to_sidecar(&app, payload).map_err(|e| e.to_string())
}
