use super::TranscriptionResult;
use serde::{Deserialize, Serialize};
use std::time::Instant;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

/// Available whisper models
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WhisperModel {
    pub id: String,
    pub name: String,
    pub size: String,
    pub description: String,
    pub url: String,
    pub filename: String,
}

pub fn available_models() -> Vec<WhisperModel> {
    vec![
        WhisperModel {
            id: "tiny".into(),
            name: "Tiny".into(),
            size: "75 MB".into(),
            description: "Fastest, lowest accuracy. Good for quick tests.".into(),
            url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin".into(),
            filename: "ggml-tiny.bin".into(),
        },
        WhisperModel {
            id: "base".into(),
            name: "Base".into(),
            size: "142 MB".into(),
            description: "Good balance of speed and accuracy. Recommended.".into(),
            url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin".into(),
            filename: "ggml-base.bin".into(),
        },
        WhisperModel {
            id: "small".into(),
            name: "Small".into(),
            size: "466 MB".into(),
            description: "Better accuracy, especially for non-English.".into(),
            url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin".into(),
            filename: "ggml-small.bin".into(),
        },
        WhisperModel {
            id: "medium".into(),
            name: "Medium".into(),
            size: "1.5 GB".into(),
            description: "High accuracy, slower. Great for multilingual.".into(),
            url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin".into(),
            filename: "ggml-medium.bin".into(),
        },
        WhisperModel {
            id: "large-v3-turbo".into(),
            name: "Large V3 Turbo".into(),
            size: "1.6 GB".into(),
            description: "Best accuracy with optimized speed. Premium.".into(),
            url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin".into(),
            filename: "ggml-large-v3-turbo.bin".into(),
        },
    ]
}

/// Get the path to the models directory
pub fn models_dir() -> std::path::PathBuf {
    let base = dirs::data_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
    base.join("clarion").join("models")
}

/// Get download status for all models
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelStatus {
    pub id: String,
    pub name: String,
    pub size: String,
    pub description: String,
    pub downloaded: bool,
}

pub fn get_models_status() -> Vec<ModelStatus> {
    let dir = models_dir();
    available_models()
        .into_iter()
        .map(|m| ModelStatus {
            downloaded: dir.join(&m.filename).exists(),
            id: m.id,
            name: m.name,
            size: m.size,
            description: m.description,
        })
        .collect()
}

/// Download a specific model
pub async fn download_model(model_id: &str, on_progress: impl Fn(u64, u64)) -> Result<(), String> {
    let models = available_models();
    let model = models
        .iter()
        .find(|m| m.id == model_id)
        .ok_or_else(|| format!("Unknown model: {model_id}"))?;

    let dir = models_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("Failed to create models dir: {e}"))?;

    let dest = dir.join(&model.filename);
    let client = reqwest::Client::new();

    log::info!("Downloading model {} from {}", model.name, model.url);

    let response = client
        .get(&model.url)
        .send()
        .await
        .map_err(|e| format!("Download request failed: {e}"))?;

    if !response.status().is_success() {
        return Err(format!("Download failed: HTTP {}", response.status()));
    }

    let total = response.content_length().unwrap_or(0);
    on_progress(0, total);

    let bytes = response
        .bytes()
        .await
        .map_err(|e| format!("Failed to download model: {e}"))?;

    on_progress(bytes.len() as u64, total);

    std::fs::write(&dest, &bytes).map_err(|e| format!("Failed to write model: {e}"))?;

    log::info!(
        "Model '{}' downloaded to {} ({} bytes)",
        model.name,
        dest.display(),
        bytes.len()
    );
    Ok(())
}

/// Delete a downloaded model
pub fn delete_model(model_id: &str) -> Result<(), String> {
    let models = available_models();
    let model = models
        .iter()
        .find(|m| m.id == model_id)
        .ok_or_else(|| format!("Unknown model: {model_id}"))?;

    let path = models_dir().join(&model.filename);
    if path.exists() {
        std::fs::remove_file(&path).map_err(|e| format!("Failed to delete model: {e}"))?;
        log::info!("Deleted model '{}'", model.name);
    }
    Ok(())
}

/// Transcribe WAV audio bytes using local whisper.cpp
pub fn transcribe(audio_wav: &[u8], model_id: &str) -> Result<TranscriptionResult, String> {
    let start = Instant::now();

    let models = available_models();
    let model = models
        .iter()
        .find(|m| m.id == model_id)
        .ok_or_else(|| format!("Unknown model: {model_id}"))?;

    let model_path = models_dir().join(&model.filename);
    if !model_path.exists() {
        return Err(format!(
            "Model '{}' not downloaded. Download it from Settings.",
            model.name
        ));
    }

    let samples = decode_wav_to_f32(audio_wav)?;

    let ctx = WhisperContext::new_with_params(
        model_path.to_str().unwrap_or_default(),
        WhisperContextParameters::default(),
    )
    .map_err(|e| format!("Failed to load whisper model: {e}"))?;

    let mut state = ctx
        .create_state()
        .map_err(|e| format!("Failed to create whisper state: {e}"))?;

    let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
    params.set_language(Some("auto"));
    params.set_print_special(false);
    params.set_print_progress(false);
    params.set_print_realtime(false);
    params.set_print_timestamps(false);
    params.set_suppress_blank(true);
    params.set_n_threads(4);

    state
        .full(params, &samples)
        .map_err(|e| format!("Whisper inference failed: {e}"))?;

    let num_segments = state
        .full_n_segments()
        .map_err(|e| format!("Failed to get segments: {e}"))?;
    let mut text = String::new();
    for i in 0..num_segments {
        if let Ok(segment) = state.full_get_segment_text(i) {
            text.push_str(&segment);
        }
    }

    let text = text.trim().to_string();
    let duration_ms = start.elapsed().as_millis() as u64;

    log::info!(
        "Local whisper ({}): {} chars in {}ms",
        model.name,
        text.len(),
        duration_ms
    );

    Ok(TranscriptionResult {
        text,
        language: None,
        duration_ms,
    })
}

fn decode_wav_to_f32(wav_bytes: &[u8]) -> Result<Vec<f32>, String> {
    let cursor = std::io::Cursor::new(wav_bytes);
    let mut reader =
        hound::WavReader::new(cursor).map_err(|e| format!("Failed to read WAV: {e}"))?;

    let samples: Vec<f32> = match reader.spec().sample_format {
        hound::SampleFormat::Int => reader
            .samples::<i16>()
            .filter_map(|s| s.ok())
            .map(|s| s as f32 / 32768.0)
            .collect(),
        hound::SampleFormat::Float => reader.samples::<f32>().filter_map(|s| s.ok()).collect(),
    };

    Ok(samples)
}
