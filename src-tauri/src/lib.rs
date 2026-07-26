mod audio;
mod context;
mod hotkey;
mod paste;
mod structure;
mod transcribe;

use audio::recorder::RecordingHandle;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use tauri_plugin_store::StoreExt;

// ── App State ──

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AppPhase {
    Idle,
    Recording,
    Transcribing,
    Structuring,
    Done,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TranscriptionProvider {
    Cloud,
    Local,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub openai_api_key: String,
    pub anthropic_api_key: String,
    pub preprocess_model: String,
    pub project_dir: Option<String>,
    pub shortcut: String,
    pub transcription_provider: TranscriptionProvider,
    pub whisper_model: String,
    pub auto_paste: bool,
    #[serde(default)]
    pub audio_device: Option<String>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            openai_api_key: std::env::var("OPENAI_API_KEY").unwrap_or_default(),
            anthropic_api_key: std::env::var("ANTHROPIC_API_KEY").unwrap_or_default(),
            preprocess_model: "claude-haiku-4-5-20251001".to_string(),
            project_dir: None,
            shortcut: "CmdOrCtrl+Shift+Space".to_string(),
            transcription_provider: TranscriptionProvider::Cloud,
            whisper_model: "base".to_string(),
            auto_paste: true,
            audio_device: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub original: String,
    pub structured: String,
    pub timestamp: u64,
}

pub struct AppState {
    pub phase: Mutex<AppPhase>,
    pub recording_handle: Mutex<Option<RecordingHandle>>,
    pub config: Mutex<AppConfig>,
    pub history: Mutex<Vec<HistoryEntry>>,
}

// ── Tauri Commands (IPC) ──

#[tauri::command]
fn get_phase(state: tauri::State<'_, AppState>) -> AppPhase {
    *state.phase.lock().unwrap()
}

#[tauri::command]
fn get_config(state: tauri::State<'_, AppState>) -> AppConfig {
    state.config.lock().unwrap().clone()
}

#[tauri::command]
fn update_config(
    app: AppHandle,
    state: tauri::State<'_, AppState>,
    config: AppConfig,
) {
    // Persist to store
    if let Ok(store) = app.store("config.json") {
        let _ = store.set("config", serde_json::to_value(&config).unwrap_or_default());
    }
    *state.config.lock().unwrap() = config;
}

#[tauri::command]
fn get_history(state: tauri::State<'_, AppState>) -> Vec<HistoryEntry> {
    state.history.lock().unwrap().clone()
}

#[tauri::command]
fn copy_to_clipboard(text: String) -> Result<(), String> {
    paste::copy_only(&text)
}

#[tauri::command]
fn get_models_status() -> Vec<transcribe::whisper_local::ModelStatus> {
    transcribe::whisper_local::get_models_status()
}

#[tauri::command]
async fn download_whisper_model(app: AppHandle, model_id: String) -> Result<(), String> {
    let _ = app.emit("model-download-started", &model_id);
    transcribe::whisper_local::download_model(&model_id, |downloaded, total| {
        let _ = app.emit("model-download-progress", (downloaded, total));
    })
    .await?;
    let _ = app.emit("model-download-complete", &model_id);
    Ok(())
}

#[tauri::command]
fn delete_whisper_model(model_id: String) -> Result<(), String> {
    transcribe::whisper_local::delete_model(&model_id)
}

#[tauri::command]
fn list_audio_devices() -> Vec<audio::recorder::AudioDevice> {
    audio::recorder::list_input_devices()
}

// ── Pipeline ──

fn reset_to_idle_after(app: &AppHandle, secs: u64) {
    let app_clone = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(secs));
        set_phase(&app_clone, AppPhase::Idle);
        let _ = app_clone.emit("phase-changed", AppPhase::Idle);
    });
}

async fn run_pipeline(app: AppHandle) {
    // Get the recording handle and stop recording
    let handle = {
        let state = app.state::<AppState>();
        let h = state.recording_handle.lock().unwrap().take();
        h
    };

    let audio_data = match handle {
        Some(h) => match h.stop() {
            Ok(data) => data,
            Err(e) => {
                log::error!("Failed to stop recording: {e}");
                set_phase(&app, AppPhase::Error);
                let _ = app.emit(
                    "pipeline-error",
                    format!("{e}. Hold the shortcut longer (at least 1 second)."),
                );
                reset_to_idle_after(&app, 3);
                return;
            }
        },
        None => {
            log::error!("No active recording");
            set_phase(&app, AppPhase::Error);
            reset_to_idle_after(&app, 3);
            return;
        }
    };

    log::info!("Audio captured: {} bytes", audio_data.len());

    // Step 1: Transcribe
    set_phase(&app, AppPhase::Transcribing);
    let _ = app.emit("phase-changed", AppPhase::Transcribing);

    let config = app.state::<AppState>().config.lock().unwrap().clone();

    let transcription_result = match config.transcription_provider {
        TranscriptionProvider::Cloud => {
            transcribe::whisper_api::transcribe(&audio_data, &config.openai_api_key).await
        }
        TranscriptionProvider::Local => {
            // Run local whisper on a blocking thread (it's CPU-bound)
            let audio = audio_data.clone();
            let model_id = config.whisper_model.clone();
            match tokio::task::spawn_blocking(move || transcribe::whisper_local::transcribe(&audio, &model_id))
                .await
            {
                Ok(result) => result,
                Err(e) => Err(format!("Whisper task failed: {e}")),
            }
        }
    };

    let transcription = match transcription_result {
            Ok(t) => {
                log::info!(
                    "Transcription complete ({:?}): {} chars, lang={:?}, {}ms",
                    config.transcription_provider,
                    t.text.len(),
                    t.language,
                    t.duration_ms
                );
                let _ = app.emit("transcription-done", &t.text);
                t
            }
            Err(e) => {
                log::error!("Transcription failed: {e}");
                set_phase(&app, AppPhase::Error);
                let _ = app.emit("pipeline-error", &e);
                reset_to_idle_after(&app, 5);
                return;
            }
        };

    // Step 2: Structure
    set_phase(&app, AppPhase::Structuring);
    let _ = app.emit("phase-changed", AppPhase::Structuring);

    let project_context = config
        .project_dir
        .as_ref()
        .map(|dir| context::load_project_context(dir));

    let structured = match structure::claude::structure_prompt(
        &transcription.text,
        &config.preprocess_model,
        &config.anthropic_api_key,
        project_context.as_ref(),
    )
    .await
    {
        Ok(result) => {
            log::info!("Structuring complete: {} chars", result.structured.len());
            result
        }
        Err(e) => {
            log::error!("Structuring failed: {e}");
            set_phase(&app, AppPhase::Error);
            let _ = app.emit("pipeline-error", &e);
            reset_to_idle_after(&app, 5);
            return;
        }
    };

    // Step 3: Copy to clipboard (and optionally auto-paste)
    let copy_result = if config.auto_paste {
        paste::copy_and_paste(&structured.structured)
    } else {
        paste::copy_only(&structured.structured)
    };
    if let Err(e) = copy_result {
        log::error!("Clipboard failed: {e}");
    }

    // Step 4: Add to history
    {
        let state = app.state::<AppState>();
        let entry = HistoryEntry {
            original: structured.original.clone(),
            structured: structured.structured.clone(),
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
        };
        let mut history = state.history.lock().unwrap();
        history.insert(0, entry);
        if history.len() > 50 {
            history.truncate(50);
        }
    }

    set_phase(&app, AppPhase::Done);
    let _ = app.emit("pipeline-complete", &structured);
    let _ = app.emit("phase-changed", AppPhase::Done);

    reset_to_idle_after(&app, 3);
}

fn set_phase(app: &AppHandle, phase: AppPhase) {
    let state = app.state::<AppState>();
    *state.phase.lock().unwrap() = phase;
}

// ── Setup ──

fn setup_tray(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let show = MenuItemBuilder::with_id("show", "Show Clarion").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit Clarion").build(app)?;
    let menu = MenuBuilder::new(app).items(&[&show, &quit]).build()?;

    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .tooltip("Clarion — Voice to Prompt")
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                toggle_window(app);
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click { .. } = event {
                toggle_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

fn toggle_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn setup_global_shortcut(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let shortcut: Shortcut = hotkey::get_default_shortcut().parse()?;

    app.global_shortcut().on_shortcut(
        shortcut,
        move |app, _shortcut, event| {
            let state = app.state::<AppState>();

            match event.state {
                ShortcutState::Pressed => {
                    let current_phase = *state.phase.lock().unwrap();
                    if current_phase != AppPhase::Idle {
                        log::info!("Ignoring hotkey — currently in {:?} phase", current_phase);
                        return;
                    }

                    log::info!("Hotkey pressed — starting recording");

                    let device = state.config.lock().unwrap().audio_device.clone();
                    match audio::recorder::start_recording(device) {
                        Ok(handle) => {
                            *state.recording_handle.lock().unwrap() = Some(handle);
                            set_phase(app, AppPhase::Recording);
                            let _ = app.emit("phase-changed", AppPhase::Recording);
                        }
                        Err(e) => {
                            log::error!("Failed to start recording: {e}");
                            let _ = app.emit("pipeline-error", &e);
                        }
                    }
                }
                ShortcutState::Released => {
                    let current_phase = *state.phase.lock().unwrap();
                    if current_phase != AppPhase::Recording {
                        return;
                    }

                    log::info!("Hotkey released — processing");

                    let app_handle = app.clone();
                    std::thread::spawn(move || {
                        let rt = tokio::runtime::Runtime::new().unwrap();
                        rt.block_on(run_pipeline(app_handle));
                    });
                }
            }
        },
    )?;

    log::info!(
        "Global shortcut registered: {}",
        hotkey::get_default_shortcut()
    );
    Ok(())
}

// ── Entry Point ──

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Load .env from the project root (one level up from src-tauri)
    let _ = dotenvy::dotenv();

    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_store::Builder::new().build())
        .manage(AppState {
            phase: Mutex::new(AppPhase::Idle),
            recording_handle: Mutex::new(None),
            config: Mutex::new(AppConfig::default()),
            history: Mutex::new(Vec::new()),
        })
        .invoke_handler(tauri::generate_handler![
            get_phase,
            get_config,
            update_config,
            get_history,
            copy_to_clipboard,
            get_models_status,
            download_whisper_model,
            delete_whisper_model,
            list_audio_devices,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            // Load persisted config from store
            if let Ok(store) = handle.store("config.json") {
                if let Some(val) = store.get("config") {
                    if let Ok(saved_config) = serde_json::from_value::<AppConfig>(val) {
                        let state = handle.state::<AppState>();
                        let mut config = state.config.lock().unwrap();
                        // Only override if store has non-empty keys (prefer store over .env)
                        if !saved_config.openai_api_key.is_empty() {
                            config.openai_api_key = saved_config.openai_api_key;
                        }
                        if !saved_config.anthropic_api_key.is_empty() {
                            config.anthropic_api_key = saved_config.anthropic_api_key;
                        }
                        config.preprocess_model = saved_config.preprocess_model;
                        config.project_dir = saved_config.project_dir;
                        config.shortcut = saved_config.shortcut;
                        config.transcription_provider = saved_config.transcription_provider;
                        config.whisper_model = saved_config.whisper_model;
                        config.auto_paste = saved_config.auto_paste;
                        config.audio_device = saved_config.audio_device;
                        log::info!("Loaded config from store");
                    }
                }
            }

            setup_tray(&handle)?;
            setup_global_shortcut(&handle)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Clarion");
}
