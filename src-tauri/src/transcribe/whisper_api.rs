use super::TranscriptionResult;
use reqwest::multipart;
use serde::Deserialize;
use std::time::Instant;

#[derive(Deserialize)]
struct WhisperResponse {
    text: String,
    language: Option<String>,
}

pub async fn transcribe(audio_wav: &[u8], api_key: &str) -> Result<TranscriptionResult, String> {
    let start = Instant::now();

    let part = multipart::Part::bytes(audio_wav.to_vec())
        .file_name("audio.wav")
        .mime_str("audio/wav")
        .map_err(|e| format!("Failed to create multipart: {e}"))?;

    let form = multipart::Form::new()
        .text("model", "whisper-1")
        .text("response_format", "verbose_json")
        .part("file", part);

    let client = reqwest::Client::new();
    let response = client
        .post("https://api.openai.com/v1/audio/transcriptions")
        .bearer_auth(api_key)
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Whisper API request failed: {e}"))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        return Err(format!("Whisper API error ({status}): {body}"));
    }

    let result: WhisperResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse Whisper response: {e}"))?;

    Ok(TranscriptionResult {
        text: result.text,
        language: result.language,
        duration_ms: start.elapsed().as_millis() as u64,
    })
}
