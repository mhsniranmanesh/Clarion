//! Cohere Chat v2 backend for the structuring layer.
//!
//! Works with any model served by the Chat endpoint, including the Command
//! family and the 3.35B Tiny Aya multilingual models.

use super::{build_system_prompt, build_user_message, StructureResult, MAX_TOKENS, TEMPERATURE};
use crate::context::ProjectContext;
use serde::{Deserialize, Serialize};

const API_URL: &str = "https://api.cohere.com/v2/chat";

#[derive(Serialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ApiRequest {
    model: String,
    messages: Vec<Message>,
    temperature: f32,
    max_tokens: u32,
    stream: bool,
}

#[derive(Deserialize)]
struct ContentBlock {
    #[serde(rename = "type")]
    block_type: String,
    text: Option<String>,
}

#[derive(Deserialize)]
struct ResponseMessage {
    content: Vec<ContentBlock>,
}

#[derive(Deserialize)]
struct ApiResponse {
    message: ResponseMessage,
}

pub async fn structure_prompt(
    raw_text: &str,
    model: &str,
    api_key: &str,
    context: Option<&ProjectContext>,
) -> Result<StructureResult, String> {
    if api_key.trim().is_empty() {
        return Err("Cohere API key is not set. Add it in Settings.".to_string());
    }

    let request = ApiRequest {
        model: model.to_string(),
        messages: vec![
            Message {
                role: "system".to_string(),
                content: build_system_prompt(context),
            },
            Message {
                role: "user".to_string(),
                content: build_user_message(raw_text),
            },
        ],
        temperature: TEMPERATURE,
        max_tokens: MAX_TOKENS,
        stream: false,
    };

    let client = reqwest::Client::new();
    let response = client
        .post(API_URL)
        .bearer_auth(api_key)
        .header("content-type", "application/json")
        .json(&request)
        .send()
        .await
        .map_err(|e| format!("Cohere API request failed: {e}"))?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        return Err(format!("Cohere API error ({status}): {body}"));
    }

    let result: ApiResponse = response
        .json()
        .await
        .map_err(|e| format!("Failed to parse Cohere response: {e}"))?;

    let structured = result
        .message
        .content
        .iter()
        .find(|block| block.block_type == "text")
        .and_then(|block| block.text.clone())
        .unwrap_or_else(|| raw_text.to_string());

    Ok(StructureResult {
        original: raw_text.to_string(),
        structured,
    })
}
