# legacy/

The original Clarion: a TypeScript CLI that piped a recorded WAV through Whisper and an
LLM from the terminal. It worked, but it could not be a hold-to-talk global shortcut that
pastes into whatever app you're in — which is the whole point — so it was rewritten as the
Tauri app in `src-tauri/` and `src/`.

**This is dead code.** Nothing builds it, nothing tests it, and it is not part of the
shipping app. It is kept because the pipeline decomposition here is easier to read than
the Rust version — `preprocess/structurer.ts` in particular is the clearest statement of
what the structuring step is supposed to do, unencumbered by IPC and state machinery.

If you're looking for how Clarion actually works today, start at `run_pipeline()` in
`src-tauri/src/lib.rs`.
