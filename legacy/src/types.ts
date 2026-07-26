export interface ClarionConfig {
  /** Model to use for preprocessing (e.g., "claude-haiku-4-5-20251001") */
  preprocessModel: string;
  /** Path to project directory for context injection */
  projectDir?: string;
  /** Files to read for project context (e.g., CLAUDE.md, README.md) */
  contextFiles: string[];
  /** Whether to auto-copy result to clipboard */
  copyToClipboard: boolean;
  /** Source language hint (e.g., "farsi", "spanish", "auto") */
  sourceLanguage: string;
}

export interface TranscriptionResult {
  text: string;
  language?: string;
  duration: number;
}

export interface PreprocessResult {
  original: string;
  structured: string;
  language: string;
}

export interface ProjectContext {
  projectName?: string;
  files: { path: string; content: string }[];
}
