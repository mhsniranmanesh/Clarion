# Contributing to Clarion

Issues and pull requests are welcome. This file covers what CI checks and the handful of
invariants that fail *silently* if you break them — those are worth reading before you
touch the pipeline or the eval harness.

## Getting set up

```bash
# Prerequisites: Rust, Node.js 18+, cmake (whisper-rs builds whisper.cpp from source)
npm install
cp .env.example .env      # add your own API keys
npm run tauri:dev
```

For the evaluation harness:

```bash
cd eval
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m pytest tests -q          # offline, no API keys needed
```

## Before you open a PR

CI runs exactly these. Running them locally first is faster than a round trip:

```bash
npm run check                                              # svelte-check + tsc

cargo fmt   --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test  --manifest-path src-tauri/Cargo.toml

(cd eval && .venv/bin/python -m pytest tests -q)
```

## Invariants

These are the places where a reasonable-looking change compiles, passes review, and is
wrong at runtime or quietly invalidates published numbers.

**The system prompt is shared verbatim between the app and the eval harness.**
`prompts/structure_system.txt` is compiled into Rust with `include_str!` and read from
disk by Python. `TEMPERATURE` (0.3) and `MAX_TOKENS` (1024) in
`src-tauri/src/structure/mod.rs` are mirrored in `eval/clarion_eval/providers.py`.
`eval/tests/test_parity.py` fails if any of the three drift. Change one side and you have
to change the other — otherwise every published benchmark number becomes a measurement of
something the app no longer does.

**Rust and TypeScript types are hand-mirrored.** `AppConfig`, `HistoryEntry`, `AppPhase`,
`ModelStatus` and `AudioDevice` are declared in Rust *and* re-declared as TypeScript
interfaces at the top of `src/App.svelte`. There is no codegen. Rename a field on one side
and the other breaks at runtime with no compile error anywhere.

**New `AppConfig` fields need `#[serde(default = "...")]`.** Config is loaded in `setup()`
by deserializing the persisted store. A field without a default makes the whole
deserialize fail for anyone upgrading from an older build, and the error is swallowed —
they silently get default settings back. The field must also be copied explicitly in the
merge block in `setup()`, and added to the TypeScript interface *and* its initializer.

**New Tauri commands must be registered** in `invoke_handler![]` in `lib.rs`. Frontend
calls go through `invoke('command_name')`; a typo is a runtime error only.

**Eval results are only as good as the dataset's review status.** Utterances carry
`author` (`native` / `llm_drafted`) and `review_status` (`native_reviewed` / `unreviewed`)
separately, and publishability is tracked per language. Today only Persian is reviewed. If
you add a language, add it to `eval/clarion_eval/languages.py` with an honest `detection`
method — `script` is exact, `function_words` is a heuristic and must be labelled as one in
the report.

## Conventions

- **Svelte 5 runes** (`$state`, `$derived`), not stores. `svelte-check` must pass clean.
- **Rust errors cross the IPC boundary as `Result<T, String>`.** User-facing failures are
  emitted as `pipeline-error` events, not returned.
- **Logging** via `log::info!` / `log::error!` (`tauri-plugin-log`), never `println!`.
- **Never log an API key**, never commit one, never let one reach `eval/runs/` output.
- **Comments explain *why*, not what.** The existing ones are load-bearing — keep that bar.
- `legacy/` is the pre-Tauri TypeScript CLI. It is dead code kept for reference; don't
  edit it.

## Reporting bugs

Include your macOS version, whether you're on a release build or `tauri:dev`, which
transcription and structuring backends are selected, and the relevant lines from the log.
Please redact API keys before pasting anything.
