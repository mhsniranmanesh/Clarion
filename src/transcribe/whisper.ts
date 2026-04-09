import fs from "node:fs";
import OpenAI from "openai";
import type { TranscriptionResult } from "../types.js";

const openai = new OpenAI();

export async function transcribeAudio(
  audioPath: string,
): Promise<TranscriptionResult> {
  const start = Date.now();

  const response = await openai.audio.transcriptions.create({
    file: fs.createReadStream(audioPath),
    model: "whisper-1",
    response_format: "verbose_json",
  });

  return {
    text: response.text,
    language: response.language,
    duration: Date.now() - start,
  };
}
