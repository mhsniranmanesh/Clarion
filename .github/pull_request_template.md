## What this changes

<!-- And why. If it fixes an issue, "Fixes #123". -->

## Checks

- [ ] `npm run check`
- [ ] `cargo fmt --manifest-path src-tauri/Cargo.toml`
- [ ] `cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings`
- [ ] `cargo test --manifest-path src-tauri/Cargo.toml`
- [ ] `(cd eval && .venv/bin/python -m pytest tests -q)`

## Invariants touched

<!-- Delete any that don't apply. See CONTRIBUTING.md. -->

- [ ] Changed the system prompt, `TEMPERATURE`, or `MAX_TOKENS` — updated **both** the app
      and `eval/`, and `test_parity.py` passes
- [ ] Added or renamed an `AppConfig` field — added `#[serde(default)]`, copied it in the
      `setup()` merge block, and updated the TypeScript interface *and* its initializer
- [ ] Added a Tauri command — registered it in `invoke_handler![]`
- [ ] Changed eval scoring or the dataset — publishability per language is still reported
      honestly

## Notes

<!-- Anything a reviewer would otherwise have to reverse-engineer. -->
