pub mod claude;
pub mod cohere;

use crate::context::ProjectContext;
use serde::{Deserialize, Serialize};

/// The structuring system prompt, shared verbatim by every provider and by the
/// offline evaluation harness in `eval/`. It lives in a single file at the repo
/// root so a benchmark can never drift from what the app actually ships.
pub const SYSTEM_PROMPT: &str = include_str!("../../../prompts/structure_system.txt");

/// Fixed across providers. Structuring is a translation-shaped task, not a
/// creative one, and holding this constant is what makes cross-provider
/// comparisons meaningful.
pub const TEMPERATURE: f32 = 0.3;

pub const MAX_TOKENS: u32 = 1024;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StructureProvider {
    Anthropic,
    Cohere,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StructureResult {
    pub original: String,
    pub structured: String,
}

/// Builds the full system prompt: the shared base, plus project context when the
/// user has pointed Clarion at a directory.
pub fn build_system_prompt(context: Option<&ProjectContext>) -> String {
    let mut prompt = String::from(SYSTEM_PROMPT.trim_end());

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

/// The user-turn wrapper around the raw transcription. Shared by every provider
/// for the same reason as the system prompt.
pub fn build_user_message(raw_text: &str) -> String {
    format!("Raw voice transcription:\n\n\"{raw_text}\"\n\nStructured English prompt:")
}

/// Dispatches to the configured provider.
pub async fn structure_prompt(
    provider: StructureProvider,
    raw_text: &str,
    model: &str,
    api_key: &str,
    context: Option<&ProjectContext>,
) -> Result<StructureResult, String> {
    match provider {
        StructureProvider::Anthropic => {
            claude::structure_prompt(raw_text, model, api_key, context).await
        }
        StructureProvider::Cohere => {
            cohere::structure_prompt(raw_text, model, api_key, context).await
        }
    }
}
