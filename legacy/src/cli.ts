#!/usr/bin/env node
import { program } from "commander";
import chalk from "chalk";
import { execSync } from "node:child_process";
import { transcribeAudio } from "./transcribe/whisper.js";
import { structurePrompt } from "./preprocess/structurer.js";
import { loadProjectContext } from "./context/loader.js";
import type { ClarionConfig } from "./types.js";

const DEFAULT_CONFIG: ClarionConfig = {
  preprocessModel: "claude-haiku-4-5-20251001",
  contextFiles: ["CLAUDE.md", "README.md", "package.json"],
  copyToClipboard: true,
  sourceLanguage: "auto",
};

program
  .name("clarion")
  .description(
    "Voice-to-prompt preprocessor — speak naturally, get structured prompts",
  )
  .version("0.1.0");

program
  .command("process")
  .description("Process a voice recording into a structured prompt")
  .argument("<audio-file>", "Path to audio file (mp3, wav, m4a, etc.)")
  .option("-p, --project <dir>", "Project directory for context", process.cwd())
  .option(
    "-m, --model <model>",
    "Preprocessing model",
    DEFAULT_CONFIG.preprocessModel,
  )
  .option("--no-clipboard", "Don't copy result to clipboard")
  .action(async (audioFile: string, opts) => {
    try {
      // Step 1: Transcribe
      console.log(chalk.dim("Transcribing audio..."));
      const transcription = await transcribeAudio(audioFile);
      console.log(chalk.dim(`Detected language: ${transcription.language}`));
      console.log(
        chalk.dim(`Transcription time: ${transcription.duration}ms\n`),
      );

      console.log(chalk.yellow("--- Raw transcription ---"));
      console.log(transcription.text);
      console.log();

      // Step 2: Load project context
      const context = opts.project
        ? loadProjectContext(opts.project)
        : undefined;

      // Step 3: Structure the prompt
      console.log(chalk.dim("Structuring prompt..."));
      const result = await structurePrompt(
        transcription.text,
        opts.model,
        context,
      );

      console.log(chalk.green("\n--- Structured prompt ---"));
      console.log(result.structured);

      // Step 4: Copy to clipboard
      if (opts.clipboard) {
        try {
          execSync("pbcopy", { input: result.structured });
          console.log(chalk.dim("\nCopied to clipboard."));
        } catch {
          // pbcopy is macOS-only, fail silently on other platforms
        }
      }
    } catch (err) {
      console.error(chalk.red("Error:"), (err as Error).message);
      process.exit(1);
    }
  });

program
  .command("text")
  .description("Process raw text (e.g., from external STT) into a structured prompt")
  .argument("<text>", "Raw text to structure")
  .option("-p, --project <dir>", "Project directory for context", process.cwd())
  .option(
    "-m, --model <model>",
    "Preprocessing model",
    DEFAULT_CONFIG.preprocessModel,
  )
  .option("--no-clipboard", "Don't copy result to clipboard")
  .action(async (text: string, opts) => {
    try {
      const context = opts.project
        ? loadProjectContext(opts.project)
        : undefined;

      console.log(chalk.dim("Structuring prompt..."));
      const result = await structurePrompt(text, opts.model, context);

      console.log(chalk.green("\n--- Structured prompt ---"));
      console.log(result.structured);

      if (opts.clipboard) {
        try {
          execSync("pbcopy", { input: result.structured });
          console.log(chalk.dim("\nCopied to clipboard."));
        } catch {
          // pbcopy is macOS-only
        }
      }
    } catch (err) {
      console.error(chalk.red("Error:"), (err as Error).message);
      process.exit(1);
    }
  });

program.parse();
