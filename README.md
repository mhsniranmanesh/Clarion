# Clarion

Voice-to-prompt desktop app — hold a shortcut, speak naturally in any language, get a well-structured English prompt pasted where your cursor is.

## How It Works

```
Hold ⌘⇧Space → speak (any language + technical terms)
    → Whisper transcribes (cloud or local)
    → an LLM restructures it into a clear English prompt
    → Result pasted into your active app
```

The structuring layer is pluggable: **Anthropic** (Claude) or **Cohere** (Command and
the 3.35B multilingual Tiny Aya models). Which one is actually better at code-switched
Persian/English developer speech is measured, not assumed — see [`eval/`](eval/).

Built with Tauri v2 (Rust backend, Svelte frontend). Lightweight (~5 MB), runs as a menu bar app.

## Install

### Download

Grab the latest `.dmg` from the [Releases page](https://github.com/mhsniranmanesh/Clarion/releases),
drag Clarion to Applications, and launch it.

On first run macOS will ask for two permissions — both are required:

- **Microphone** — to record your voice
- **Accessibility** — to paste the result into your active app

> If you see *"Clarion is damaged and can't be opened"*, the build you downloaded
> was not notarized. Run `xattr -cr /Applications/Clarion.app` to clear the
> quarantine flag, or build from source.

### From source

```bash
# Prerequisites: Rust, Node.js 18+, cmake (for local whisper)
git clone https://github.com/mhsniranmanesh/Clarion.git
cd Clarion
npm install
npm run tauri:build
```

The built app will be in `src-tauri/target/release/bundle/macos/Clarion.app`.

### Development

```bash
npm install
cp .env.example .env   # Add your API keys
npm run tauri:dev       # Launches the app with hot-reload
```

## Setup

1. Launch Clarion — it appears in your menu bar
2. Open Settings (click tray icon or use the Settings tab)
3. Enter your API keys:
   - **OpenAI API Key** — for Whisper speech-to-text (cloud mode only)
   - **Anthropic API Key** — for Claude prompt structuring
   - **Cohere API Key** *(optional)* — to use Cohere for structuring instead
4. (Optional) Switch to **Local** transcription and download a Whisper model for offline use
5. (Optional) Under Processing, switch the structuring backend between Anthropic and Cohere

Clarion only asks for the keys the providers you selected actually need — run local
Whisper with Cohere structuring and you never need an OpenAI key at all.

## Usage

1. **Hold `⌘ + ⇧ + Space`** — recording starts
2. **Speak** — in any language, mix with English technical terms
3. **Release** — Clarion transcribes, structures, and pastes the result

The structured prompt is also copied to your clipboard.

## Features

- **Multilingual** — speak in Farsi, Spanish, German, etc. mixed with English tech terms
- **Pluggable structuring** — Anthropic or Cohere, switchable in Settings
- **Cloud or Local transcription** — OpenAI Whisper API or local whisper.cpp (offline, free)
- **Model library** — choose from Tiny (75 MB) to Large V3 Turbo (1.6 GB)
- **Auto-paste** — result injected into your active app via simulated keystroke
- **Project context** — reads CLAUDE.md, README, package.json to understand your codebase
- **Prompt history** — browse and re-copy past prompts
- **Persistent settings** — API keys and preferences saved across restarts
- **Menu bar app** — click tray icon to show/hide, runs in background

## Configuration

### Environment variables (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
COHERE_API_KEY=...        # optional, for the Cohere structuring backend
```

These are used as defaults. Settings saved in the app UI take precedence.

### Local Whisper Models

Available models (downloaded on demand from Hugging Face):

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| Tiny | 75 MB | Fastest | Basic |
| Base | 142 MB | Fast | Good |
| Small | 466 MB | Moderate | Better |
| Medium | 1.5 GB | Slow | High |
| Large V3 Turbo | 1.6 GB | Moderate | Best |

Models are stored in `~/Library/Application Support/clarion/models/`.

## Tech Stack

- **Tauri v2** — app shell, system tray, global shortcuts, IPC
- **Rust** — audio capture (cpal), transcription, API calls, clipboard
- **Svelte 5** — minimal frontend UI
- **whisper-rs** — local whisper.cpp bindings
- **enigo** — cross-platform keystroke simulation

## Evaluation

Clarion's users speak one language and code in another, so the structuring layer has to
translate *and* leave code identifiers untouched. [`eval/`](eval/) measures how well
different models actually do that on code-switched Persian/English developer speech.

The primary metrics are deterministic — identifier recall (did `useState` survive
verbatim?), residual non-English script, and format compliance — so anyone can recompute
them from the committed run files and get identical numbers. Meaning and prompt quality
are judged by LLMs, blind, with one judge per vendor and their disagreement reported.

Every model gets the exact prompt and sampling settings the app ships with; a parity test
fails if the app and the harness ever drift apart.

```bash
cd eval
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m clarion_eval.run --no-judge
```

See [eval/README.md](eval/README.md) for methodology and limitations, and
[eval/RESULTS.md](eval/RESULTS.md) for results.

## Releasing

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml).
Push a tag and the workflow builds a universal macOS binary and opens a draft release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Signing and notarization are driven entirely by environment variables — no
credentials live in the repo. To produce a distributable build, set these as
GitHub Actions secrets (or export them locally before `npm run tauri:build`):

| Secret | Purpose |
|--------|---------|
| `APPLE_CERTIFICATE` | Base64-encoded Developer ID `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | Password for the `.p12` |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_PASSWORD` | App-specific password for that Apple ID |
| `APPLE_TEAM_ID` | Your Apple Developer Team ID |

Without them the build still succeeds, but the app is unsigned and users will
need to clear the quarantine flag manually (see Install above).

## Roadmap

- [ ] Custom shortcut configuration (the shortcut is currently fixed at `⌘⇧Space`)
- [ ] Auto-detect active project from VS Code / Cursor
- [ ] Auto-updater via GitHub Releases
- [ ] Windows + Linux support

## Contributing

Issues and pull requests are welcome. Before opening a PR, please run:

```bash
npm run check          # Svelte + TypeScript
cargo fmt --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml
(cd eval && .venv/bin/python -m pytest tests -q)   # eval harness
```

## License

[MIT](LICENSE)
