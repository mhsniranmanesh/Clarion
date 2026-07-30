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

/// The first `text` block, or `fallback` when the response carries none.
///
/// Cannot simply take `content[0]`: reasoning-capable models emit a `thinking`
/// block first. And when the whole token budget is spent on reasoning there is
/// no text block at all — the eval harness lost most of one judge's verdicts to
/// exactly that — so returning the raw transcription beats returning nothing.
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

    Ok(StructureResult {
        original: raw_text.to_string(),
        structured: first_text_block(&result.message.content, raw_text),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn blocks(json: &str) -> Vec<ContentBlock> {
        serde_json::from_str::<ApiResponse>(json)
            .unwrap()
            .message
            .content
    }

    #[test]
    fn reads_a_plain_text_response() {
        let parsed = blocks(r#"{"message":{"content":[{"type":"text","text":"Add a retry"}]}}"#);
        assert_eq!(first_text_block(&parsed, "raw"), "Add a retry");
    }

    #[test]
    fn skips_a_leading_thinking_block() {
        // Command A+ reasons before answering. Taking content[0] would paste the
        // model's private scratchpad into the user's editor.
        let parsed = blocks(
            r#"{"message":{"content":[
                {"type":"thinking","thinking":"The user wants..."},
                {"type":"text","text":"Add a retry"}
            ]}}"#,
        );
        assert_eq!(first_text_block(&parsed, "raw"), "Add a retry");
    }

    #[test]
    fn falls_back_to_the_transcription_when_no_text_block_arrives() {
        // Reasoning tokens come out of max_tokens, so a long enough thinking
        // block leaves no room to answer. Losing the user's words entirely is
        // the one outcome worse than an unstructured prompt.
        let parsed = blocks(r#"{"message":{"content":[{"type":"thinking","thinking":"..."}]}}"#);
        assert_eq!(
            first_text_block(&parsed, "raw transcription"),
            "raw transcription"
        );
    }

    #[test]
    fn falls_back_when_content_is_empty() {
        let parsed = blocks(r#"{"message":{"content":[]}}"#);
        assert_eq!(first_text_block(&parsed, "raw"), "raw");
    }

    #[test]
    fn request_matches_the_chat_v2_schema() {
        // Cohere takes the system prompt as a message; Anthropic takes it as a
        // top-level field. Mixing the two up yields a 400 only at runtime.
        let request = ApiRequest {
            model: "tiny-aya-earth".into(),
            messages: vec![
                Message {
                    role: "system".into(),
                    content: "sys".into(),
                },
                Message {
                    role: "user".into(),
                    content: "usr".into(),
                },
            ],
            temperature: TEMPERATURE,
            max_tokens: MAX_TOKENS,
            stream: false,
        };
        let json = serde_json::to_value(&request).unwrap();

        assert_eq!(json["model"], "tiny-aya-earth");
        assert_eq!(json["messages"][0]["role"], "system");
        assert_eq!(json["messages"][1]["role"], "user");
        assert_eq!(json["stream"], false);
        assert!(
            json.get("system").is_none(),
            "system belongs in messages, not at the top level"
        );
    }

    #[tokio::test]
    async fn a_blank_key_fails_before_any_network_call() {
        let error = structure_prompt("hello", "tiny-aya-earth", "   ", None)
            .await
            .unwrap_err();
        assert!(
            error.contains("Settings"),
            "error should tell the user where to fix it"
        );
    }
}
