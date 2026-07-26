import Anthropic from "@anthropic-ai/sdk";
import type { PreprocessResult, ProjectContext } from "../types.js";

const anthropic = new Anthropic();

function buildSystemPrompt(context?: ProjectContext): string {
  let prompt = `You are a prompt preprocessor. Your job is to take raw voice transcription — which may be in any language or a mix of languages with technical English terms — and produce a clear, well-structured English prompt ready to send to an AI coding assistant.

Rules:
- Preserve all technical terms exactly as spoken (function names, library names, error messages, etc.)
- Translate non-English parts to natural English
- Structure the output as a clear problem statement or request
- If the speaker describes a bug, format it as: what they expected, what happened, and relevant context
- If the speaker is requesting a feature, format it as: what they want, why, and any constraints mentioned
- Keep the speaker's intent and emphasis — don't add or remove meaning
- Be concise but complete`;

  if (context?.files.length) {
    prompt += `\n\nProject context (use this to understand technical terms and project-specific jargon):\n`;
    prompt += `Project: ${context.projectName}\n`;
    for (const file of context.files) {
      prompt += `\n--- ${file.path} ---\n${file.content}\n`;
    }
  }

  return prompt;
}

export async function structurePrompt(
  rawText: string,
  model: string,
  context?: ProjectContext,
): Promise<PreprocessResult> {
  const response = await anthropic.messages.create({
    model,
    max_tokens: 1024,
    system: buildSystemPrompt(context),
    messages: [
      {
        role: "user",
        content: `Raw voice transcription:\n\n"${rawText}"\n\nStructured English prompt:`,
      },
    ],
  });

  const structured =
    response.content[0].type === "text" ? response.content[0].text : rawText;

  return {
    original: rawText,
    structured,
    language: "auto",
  };
}
