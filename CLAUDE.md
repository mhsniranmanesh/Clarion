# Clarion

Voice-to-prompt macOS menu bar app. Hold `⌘⇧Space` → speak in any language → Whisper
transcribes → an LLM restructures it into an English prompt → pasted into the active app.

Tauri v2 (Rust backend) + Svelte 5 frontend. See `README.md` for user-facing docs.

## Layout

| Path | What it is |
|---|---|
| `src-tauri/src/` | Rust backend — the whole pipeline lives here |
| `src/App.svelte` | The entire frontend (one component, 3 views) |
| `prompts/structure_system.txt` | The structuring system prompt — single source of truth |
| `eval/` | Python harness measuring structuring quality across models |
| `legacy/` | The pre-Tauri TypeScript CLI. Dead code, kept for reference — do not edit |

Rust modules: `audio/` (cpal capture → WAV), `transcribe/` (whisper_api = OpenAI cloud,
whisper_local = whisper.cpp), `structure/` (claude.rs, cohere.rs behind a
`StructureProvider` enum), `context/` (reads CLAUDE.md/README/package.json from the
user's project dir), `paste/` (arboard clipboard + enigo keystroke), `hotkey/`.

The pipeline is `run_pipeline()` in `src-tauri/src/lib.rs` — record → transcribe →
structure → clipboard/paste → history. Phase transitions are emitted to the frontend as
`phase-changed` events; the frontend is a listener, it never drives the pipeline.

## Invariants — break these and things silently rot

**The prompt is shared verbatim between the app and the eval harness.**
`prompts/structure_system.txt` is pulled into Rust via `include_str!` and read by Python.
`TEMPERATURE` (0.3) and `MAX_TOKENS` (1024) in `src-tauri/src/structure/mod.rs` are
mirrored in the harness. `eval/tests/test_parity.py` fails if they ever drift. If you
change any of the three, change both sides and run that test — otherwise every published
benchmark number becomes a measurement of something the app no longer does.

**Rust and TypeScript types are hand-mirrored.** `AppConfig`, `HistoryEntry`, `AppPhase`,
`ModelStatus`, `AudioDevice` are declared in Rust *and* re-declared as TS interfaces at
the top of `src/App.svelte`. There is no codegen. Rename a field on one side and the other
side breaks at runtime with no compile error.

**New `AppConfig` fields need `#[serde(default = "...")]`.** Config is loaded in `setup()`
by deserializing the persisted store. A field without a default makes the whole
deserialize fail for anyone upgrading from an older build, and the error is swallowed —
they silently get default settings back. The field must also be copied explicitly in the
merge block in `setup()`, and added to the TS interface *and* its initializer in
`App.svelte`.

**New Tauri commands must be registered** in `invoke_handler![]` in `lib.rs`. Frontend
calls go through `invoke('command_name')` — a typo is a runtime error only.

## Conventions

- Svelte 5 runes (`$state`, `$derived`), not stores. `svelte-check` must pass clean.
- Rust errors cross the IPC boundary as `Result<T, String>`; user-facing failures are
  emitted as `pipeline-error` events, not returned.
- `log::info!` / `log::error!` via `tauri-plugin-log`, not `println!`.
- Comments explain *why*, not what. The existing ones are load-bearing — keep that bar.

## Commands

```bash
npm run tauri:dev     # Run the app with hot reload
npm run check         # svelte-check + tsc — run before every commit
npm run tauri:build   # Universal macOS bundle

cargo fmt   --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test  --manifest-path src-tauri/Cargo.toml

cd eval && .venv/bin/python -m pytest tests -q
cd eval && python -m clarion_eval.run --no-judge   # deterministic metrics only
```

`.github/workflows/ci.yml` runs all of the above on push to `main` and on every PR.
`release.yml` is separate and fires only on `v*` tags. CI is not a substitute for running
them locally — it is the same set, just later.

## Secrets

API keys come from `.env` (gitignored) as defaults, overridden by whatever the user saves
in Settings, which persists to `~/Library/Application Support/clarion/config.json` in
plaintext. Never log a key, never commit one, never add one to `eval/runs/` output.
