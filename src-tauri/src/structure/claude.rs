use super::StructureResult;
use crate::context::ProjectContext;
use serde::{Deserialize, Serialize};

#[derive(Serialize)]
struct Message {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ApiRequest {
    model: String,
    max_tokens: u32,
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

fn build_system_prompt(context: Option<&ProjectContext>) -> String {
    let mut prompt = String::from(
        "You are a prompt preprocessor. Your job is to take raw voice transcription — \
         which may be in any language or a mix of languages with technical English terms — \
         and produce a clear, well-structured English prompt ready to send to an AI coding assistant.\n\n\
         Rules:\n\
         - Preserve all technical terms exactly as spoken (function names, library names, error messages, etc.)\n\
         - Translate non-English parts to natural English\n\
         - Structure the output as a clear problem statement or request\n\
         - If the speaker describes a bug, format it as: what they expected, what happened, and relevant context\n\
         - If the speaker is requesting a feature, format it as: what they want, why, and any constraints mentioned\n\
         - Keep the speaker's intent and emphasis — don't add or remove meaning\n\
         - Be concise but complete",
    );

    if let Some(ctx) = context {
        if !ctx.files.is_empty() {
            prompt.push_str(
                "\n\nProject context (use this to understand technical terms and project-specific jargon):\n",
            );
            if let Some(name) = &ctx.project_name {
                prompt.push_str(&format!("Project: {name}\n"));
            }
            for file in &ctx.files {
                prompt.push_str(&format!("\n--- {} ---\n{}\n", file.path, file.content));
            }
        }
    }

    prompt
}

pub async fn structure_prompt(
    raw_text: &str,
    model: &str,
    api_key: &str,
    context: Option<&ProjectContext>,
) -> Result<StructureResult, String> {
    let request = ApiRequest {
        model: model.to_string(),
        max_tokens: 1024,
        system: build_system_prompt(context),
        messages: vec![Message {
            role: "user".to_string(),
            content: format!("Raw voice transcription:\n\n\"{raw_text}\"\n\nStructured English prompt:"),
        }],
    };

    let client = reqwest::Client::new();
    let response = client
        .post("https://api.anthropic.com/v1/messages")
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

    let structured = result
        .content
        .first()
        .and_then(|block| {
            if block.block_type == "text" {
                block.text.clone()
            } else {
                None
            }
        })
        .unwrap_or_else(|| raw_text.to_string());

    Ok(StructureResult {
        original: raw_text.to_string(),
        structured,
    })
}
