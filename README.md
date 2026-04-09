# Clarion

Voice-to-prompt preprocessor — speak naturally in any language, get well-structured English prompts for AI coding tools.

## The Problem

When working with AI coding assistants, better-framed prompts get dramatically better results. But when you're deep in a problem, you want to just *talk* about it — often in your native language mixed with English technical terms. Speech-to-text tools mangle this mix, and the garbled transcript wastes AI tokens on interpretation instead of problem-solving.

## How It Works

```
You speak (any language + technical terms)
    → Speech-to-text (OpenAI Whisper)
    → Preprocessing LLM (Claude Haiku)
        - Reads your project context (CLAUDE.md, README, etc.)
        - Preserves technical terms exactly as spoken
        - Restructures into a clear English prompt
    → Shows result for your review
    → Copies to clipboard
```

## Quick Start

```bash
npm install
cp .env.example .env  # Add your API keys

# From an audio file
npx clarion process recording.m4a --project /path/to/your/project

# From text (e.g., pasted from another STT tool)
npx clarion text "your raw transcription here" --project /path/to/your/project
```

## Usage

```bash
# Process audio file with project context
clarion process voice-note.mp3 --project ~/dev/my-project

# Use a different model for preprocessing
clarion process voice-note.mp3 --model claude-sonnet-4-6-20250514

# Process raw text without project context
clarion text "man mikham ye function bezanam ke ..."

# Skip clipboard copy
clarion process voice-note.mp3 --no-clipboard
```

## Configuration

Set these environment variables in `.env`:

- `ANTHROPIC_API_KEY` — for prompt preprocessing (Claude)
- `OPENAI_API_KEY` — for speech-to-text (Whisper)

## License

MIT
