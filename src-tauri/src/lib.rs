mod commands;
mod sidecar;


pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            sidecar::spawn_sidecar(app_handle)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::send_input,
            commands::run_shell_command,
            commands::set_working_directory,
            commands::interrupt_agent,
            commands::get_model_status,
            commands::get_config,
            commands::set_config,
            commands::reset_session,
            commands::load_model,
            commands::get_download_catalog,
            commands::start_model_download,
            commands::cancel_model_download,
            commands::install_browser,
            commands::send_tool_ack,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
