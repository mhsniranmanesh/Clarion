//! Anthropic Messages backend for the structuring layer.
//!
//! This is Clarion's original structuring path and serves as the baseline that
//! the `eval/` harness measures other providers against.

use super::{build_system_prompt, build_user_message, StructureResult, MAX_TOKENS, TEMPERATURE};
use crate::context::ProjectContext;
use serde::{Deserialize, Serialize};

const API_URL: &str = "https://api.anthropic.com/v1/messages";

#[derive(Serialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ApiRequest {
    model: String,
    max_tokens: u32,
    temperature: f32,
    system: String,
    messages: Vec<Message>,
}

#[derive(Deserialize)]
struct ContentBlock {
    #[serde(rename = "type")]
    block_type: String,
    text: Option<String>,
}

#[derive(Deserialize)]
struct ApiResponse {
    content: Vec<ContentBlock>,
}

/// The first `text` block, or `fallback` when the response carries none.
/// See the equivalent in `cohere.rs` — the Messages API has the same shape.
fn first_text_block(blocks: &[ContentBlock], fallback: &str) -> String {
    blocks
        .iter()
        .find(|block| block.block_type == "text")
        .and_then(|block| block.text.clone())
        .unwrap_or_else(|| fallback.to_string())
}

pub async fn structure_prompt(
    raw_text: &str,
    model: &str,
    api_key: &str,
    context: Option<&ProjectContext>,
) -> Result<StructureResult, String> {
    if api_key.trim().is_empty() {
        return Err("Anthropic API key is not set. Add it in Settings.".to_string());
    }

    let request = ApiRequest {
        model: model.to_string(),
        max_tokens: MAX_TOKENS,
        temperature: TEMPERATURE,
        system: build_system_prompt(context),
        messages: vec![Message {
            role: "user".to_string(),
            content: build_user_message(raw_text),
        }],
    };

    let client = reqwest::Client::new();
    let response = client
        .post(API_URL)
        .header("x-api-key", api_key)
        .header("anthropic-version", "2023-06-01")
        .header("content-type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Anthropic API request failed: {e}"))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        return Err(format!("Anthropic API error ({status}): {body}"));
    }

    let result: ApiResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse Anthropic response: {e}"))?;

    Ok(StructureResult {
        original: raw_text.to_string(),
        structured: first_text_block(&result.content, raw_text),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn blocks(json: &str) -> Vec<ContentBlock> {
        serde_json::from_str::<ApiResponse>(json).unwrap().content
    }

    #[test]
    fn reads_a_plain_text_response() {
        let parsed = blocks(r#"{"content":[{"type":"text","text":"Add a retry"}]}"#);
        assert_eq!(first_text_block(&parsed, "raw"), "Add a retry");
    }

    #[test]
    fn skips_a_leading_thinking_block() {
        let parsed = blocks(
            r#"{"content":[
                {"type":"thinking","thinking":"..."},
                {"type":"text","text":"Add a retry"}
            ]}"#,
        );
        assert_eq!(first_text_block(&parsed, "raw"), "Add a retry");
    }

    #[test]
    fn falls_back_to_the_transcription_when_no_text_block_arrives() {
        let parsed = blocks(r#"{"content":[{"type":"thinking","thinking":"..."}]}"#);
        assert_eq!(
            first_text_block(&parsed, "raw transcription"),
            "raw transcription"
        );
    }

    #[test]
    fn request_matches_the_messages_schema() {
        // Anthropic takes `system` at the top level, not as a message. Sending
        // it as a message is accepted and silently ignored — the model then
        // answers with no instructions at all, which is the worst failure mode:
        // a plausible-looking wrong result.
        let request = ApiRequest {
            model: "claude-haiku-4-5-20251001".into(),
            max_tokens: MAX_TOKENS,
            temperature: TEMPERATURE,
            system: "sys".into(),
            messages: vec![Message {
                role: "user".into(),
                content: "usr".into(),
            }],
        };
        let json = serde_json::to_value(&request).unwrap();

        assert_eq!(json["system"], "sys");
        assert_eq!(json["messages"].as_array().unwrap().len(), 1);
        assert_eq!(json["messages"][0]["role"], "user");
    }

    #[tokio::test]
    async fn a_blank_key_fails_before_any_network_call() {
        let error = structure_prompt("hello", "claude-haiku-4-5-20251001", "", None)
            .await
            .unwrap_err();
        assert!(
            error.contains("Settings"),
            "error should tell the user where to fix it"
        );
    }
}
