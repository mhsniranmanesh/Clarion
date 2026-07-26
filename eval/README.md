# Clarion Eval

How well do different models turn **code-switched Persian/English developer speech**
into a clean English prompt for a coding assistant?

Clarion's whole reason to exist is that its user thinks in one language and codes in
another. The structuring layer is where that gets resolved, so it is the layer worth
measuring. This harness measures it.

## What is being measured

One task, held constant across every model: take a raw voice transcription that mixes
Persian with English technical terms, and emit a structured English prompt.

Every model receives the **identical** system prompt, user message, temperature
(`0.3`) and token budget (`1024`) — the ones compiled into the shipping app, read from
[`prompts/structure_system.txt`](../prompts/structure_system.txt). `tests/test_parity.py`
fails the build if the Rust app and this harness ever drift apart. Any difference in the
results is a difference in the model, not in how it was asked.

The evaluation runs **without** project context, so scores reflect multilingual
structuring ability rather than retrieval over one particular repository.

## Metrics

### Primary — deterministic

No model in the loop. Pure functions of (input, output), recomputable from the
committed run files, byte-identical on every machine.

| Metric | Definition |
|---|---|
| **Identifier recall** | Share of technical tokens the speaker actually said that survive verbatim. Case-sensitive (`useState` ≠ `usestate`) and token-boundary aware, so `` `useState` `` and `useState()` count but `myUseStateWrapper` does not. |
| **Fully English** | Zero Persian/Arabic-script codepoints left in the output. Untranslated spans are a hard failure. |
| **Format clean** | No preamble or trailing commentary, which the shared prompt explicitly forbids. Reported separately so a small model losing points for a formatting tic is visible as such, rather than silently marked down as a worse translator. |
| **Latency** | Median wall-clock per request. |

Case-insensitive recall is tracked alongside the headline number, so "kept the word,
mangled the casing" is distinguishable from "dropped it entirely".

### Secondary — LLM-judged

Meaning preservation and prompt quality cannot be regexed, so they are judged, with
three deliberate guards:

1. **Blind.** Candidates are shuffled and relabelled `A`, `B`, `C`… per utterance. The
   judge never sees a model name.
2. **Deterministic shuffle.** The permutation is seeded from the utterance id, so
   reruns reproduce exactly.
3. **Two judges from different vendors.** Anthropic is *in* the comparison, so judging
   only with an Anthropic model would be a conflict of interest. One judge per vendor
   runs by default and the report prints their disagreement, making vendor affinity
   visible instead of hidden.

Judged scores are reported as secondary evidence. Where the two judges disagree
materially, treat them as weak.

## Setup

```bash
cd eval
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # add '.[local]' for on-device GGUF
```

Keys are read from `eval/.env` then the repo-root `.env`:

```
ANTHROPIC_API_KEY=...   # baseline + one judge
COHERE_API_KEY=...      # https://dashboard.cohere.com/api-keys (free trial keys work)
```

## Running

```bash
# Default set: Haiku baseline vs Command A+, Command A Translate, Tiny Aya Earth
python -m clarion_eval.run

# Deterministic metrics only, no judging, no judge spend
python -m clarion_eval.run --no-judge

# Everything, including both Tiny Aya variants
python -m clarion_eval.run --models haiku command-a-plus command-a-translate \
                                    tiny-aya-earth tiny-aya-global

# On-device Tiny Aya
python -m clarion_eval.run --models tiny-aya-earth-local \
                           --gguf-path ~/models/tiny-aya-earth-Q4_K_M.gguf

# Override a judge if a model ID is not available on your account
python -m clarion_eval.run --judge anthropic:<model> cohere:<model>
```

Each run writes `runs/<timestamp>/` containing `generations.jsonl`, `judgements.jsonl`,
`manifest.json` (including a SHA-256 of the exact prompt used) and a rendered
`REPORT.md`.

Throwaway runs are gitignored. To publish one:

```bash
git add -f eval/runs/<timestamp>
```

### Getting the GGUF for local runs

Tiny Aya is open-weights. Download a quantized build from Hugging Face
(`CohereLabs/tiny-aya-earth`) and pass the file path to `--gguf-path`. No filename is
hardcoded here, because quantization choice is yours.

## Honesty rules this harness enforces in code

The point of this evaluation is only worth anything if it can report a loss.

- **Nothing is dropped.** Every utterance × model pair is attempted once and recorded,
  including failures. Averages are over the *whole* dataset with failed generations
  scored zero, and every table prints `completed / total`. A model cannot look good by
  averaging over the subset that happened to work.
- **Failures are judged too**, as empty candidates. Hiding them from the judge would
  flatter models that failed.
- **Unreviewed data is refused.** Utterances carry `reviewed: true` only after a native
  speaker has checked them. The runner warns and the report prints a
  **Not publishable** banner while any remain unreviewed.
- **The dataset validates itself.** Every listed identifier must actually appear in the
  utterance text, or loading fails — otherwise recall would be measuring nothing.

## Limitations

State these wherever the results are cited.

- **n = 35.** This is a case study, not a benchmark. It will not resolve small
  differences between strong models.
- **One speaker, one dialect.** Written by a single native Persian speaker. Nothing here
  generalises to other languages, or even to other Persian speakers.
- **Author-corrected synthetic.** Utterances were drafted programmatically and then
  rewritten by a native speaker for naturalness. They are modelled on real dictation but
  are not transcripts of it.
- **Text in, text out.** Whisper is not in the loop, so ASR errors are excluded. Real
  end-to-end quality will be lower than these numbers.
- **Judge bias is mitigated, not eliminated.** Blinding and cross-vendor judging reduce
  it; they do not remove a model's affinity for its own house style.

## Why speech-to-text is not compared

Cohere ships an ASR model, `cohere-transcribe-03-2026`, which is state of the art on
English. It supports 14 languages: English, German, French, Italian, Spanish,
Portuguese, Greek, Dutch, Polish, Vietnamese, Chinese, Arabic, Japanese and Korean.

**Persian is not among them.** Swapping Clarion's Whisper layer for it would regress the
exact use case Clarion exists to serve, so the transcription layer is left on Whisper and
this evaluation is scoped to structuring. That is a finding, not an omission.

## Results

See [RESULTS.md](RESULTS.md).
