# Clarion Eval

How well do different models turn **code-switched developer speech** into a clean
English prompt for a coding assistant, across six source languages?

Clarion's whole reason to exist is that its user thinks in one language and codes in
another. The structuring layer is where that gets resolved, so it is the layer worth
measuring. This harness measures it.

## Languages

35 utterances each, 210 total. The split is not arbitrary — it is what makes Cohere's
regional-tuning claim testable.

| Code | Language | Script | Residue check | Tiny Aya region |
|---|---|---|---|---|
| `fa` | Persian | Arabic | exact | Earth — Africa + West Asia |
| `ar` | Arabic | Arabic | exact | Earth — Africa + West Asia |
| `zh` | Chinese | Han | exact | Water — Europe + Asia-Pacific |
| `ru` | Russian | Cyrillic | exact | Water — Europe + Asia-Pacific |
| `es` | Spanish | Latin | **heuristic** | Water — Europe + Asia-Pacific |
| `fr` | French | Latin | **heuristic** | Water — Europe + Asia-Pacific |

The Tiny Aya variants are the same 3.35B model over the same 70 languages, differing
only in which region they were tuned toward. Holding dataset, prompt and decoding
fixed and varying only the variant isolates what the regional tuning is actually
worth. `tiny-aya-fire` (South Asia) covers none of these six and is available as a
negative control: if Fire matches the region-matched variant everywhere, the tuning is
not doing what the model card says.

## What is being measured

One task, held constant across every model: take a raw voice transcription that mixes
a source language with English technical terms, and emit a structured English prompt.

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
| **Fully English** | No source-language text left in the output. Untranslated spans are a hard failure. See below — this one is measured two different ways. |
| **Format clean** | No preamble or trailing commentary, which the shared prompt explicitly forbids. Reported separately so a small model losing points for a formatting tic is visible as such, rather than silently marked down as a worse translator. |
| **Latency** | Median wall-clock per request. |

Case-insensitive recall is tracked alongside the headline number, so "kept the word,
mangled the casing" is distinguishable from "dropped it entirely".

#### The Latin-script problem

"Fully English" is trivial to measure for Persian, Arabic, Chinese and Russian: one
codepoint from the source script in the output is proof the model failed, and there is
no way for that check to be wrong.

Spanish and French break it. They are written in the same alphabet as English, so a
model that echoes its Spanish input **completely untranslated** produces zero non-Latin
characters and scores a perfect 100%. A script check would report the exact opposite of
the truth on the two languages most likely to tempt a model into passthrough.

So those two are detected by counting high-frequency source-language function words and
vocabulary instead — a heuristic, and labelled as one everywhere it appears
(`residual_method`, `residual_exact`, and a separate note under every report table).

Keeping it honest is a measurement problem, not an assertion:

- **Case folding makes short articles dangerous.** `los` matches "Los Angeles", `un`
  matches "UN", `est` matches "EST", `el` matches "El Paso". Two more survive as English
  borrowings outright — `de` in "de facto", `la` in "à la carte". All are excluded, and
  the lists lean on unambiguous developer vocabulary (`columna`, `requête`, `pantalla`,
  `fichier`) instead.
- **French elision does the heavy lifting.** `l'endpoint`, `d'environnement`, `qu'on` —
  a lone word-initial letter before an apostrophe is near-perfect French, and it catches
  sentences no word list would. English contractions cannot collide: they elide *after*
  the stem (`don't`, `we've`), and `o'clock` uses a letter deliberately left out of the set.
- **The word lists are tested, not trusted.** `tests/test_languages.py` runs both
  detectors over all 210 English glosses plus an adversarial English corpus and fails on
  a single false positive, then checks every Spanish and French utterance trips its own
  detector with margin. Current margin: minimum 3 markers per row, median 6–7. Adding a
  marker that collides with English breaks the suite immediately.

Treat Spanish and French residue numbers as slightly softer than the other four. That is
why the report prints which method produced each column.

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
# Default: 6 models x 210 utterances x 6 languages, judged
python -m clarion_eval.run

# Deterministic metrics only, no judging, no judge spend
python -m clarion_eval.run --no-judge

# One language
python -m clarion_eval.run --langs fa --no-judge

# The regional-tuning experiment on its own
python -m clarion_eval.run --models tiny-aya-earth tiny-aya-water \
                                    tiny-aya-fire tiny-aya-global

# Cheap smoke test — 3 utterances per language, all six languages covered
python -m clarion_eval.run --no-judge --limit 3

# On-device Tiny Aya
python -m clarion_eval.run --models tiny-aya-earth-local \
                           --gguf-path ~/models/tiny-aya-earth-Q4_K_M.gguf

# Override a judge if a model ID is not available on your account
python -m clarion_eval.run --judge anthropic:<model> cohere:<model>
```

`--limit` caps *per language*, so a small smoke run still covers all six rather than
returning 5 Arabic rows and nothing else.

### Preflight and pacing

Every run probes each model and judge with a one-token request before generating, and
aborts if any is unreachable:

```
Preflight...
  ok   haiku                    claude-haiku-4-5-20251001
  FAIL judge:judge-anthropic    claude-sonnet-4-6-20250514
```

A full six-language run is more than 1,600 requests. Discovering a dead model ID at the
end of that is an hour lost to a typo — and the worst case is a bad *judge* ID, which
surfaces only after every generation has already succeeded. Eight one-token requests up
front is cheap insurance. `--no-preflight` skips it.

Requests are also paced, because Cohere trial keys allow only **20 calls per minute** and
one run issues well over a thousand. Without pacing most come back `429` and the report
records a rate limit as though it were a model failure. Raise the cap on a production key:

```bash
CLARION_EVAL_COHERE_RPM=30 python -m clarion_eval.run
```

The default is 20, which is trial-key safe. 30 per model is what a production key
sustained in practice; the observed ceiling was around 40, so this leaves headroom (see
*per model* below — the aggregate is five times this figure).

Retries use exponential backoff with jitter and honour `Retry-After`. A retried request
is not a failed one — the error is recorded only once attempts are exhausted.

### Trial keys cannot complete a full run

Cohere trial keys carry a **second, harder cap: 1,000 API calls per month**, account-wide.
A full six-language run needs ~1,260 Cohere calls for generation alone, plus ~210 more if
the Cohere judge is enabled. A trial key will therefore die partway through, and no amount
of pacing helps — pacing solves the per-minute limit, not the monthly one.

`429` is used for both, so the harness reads the body to tell them apart: a per-minute
limit is retried with backoff, an exhausted monthly quota fails immediately. Retrying the
latter six times each turns instant permanent failures into ~45-second ones, which across
hundreds of remaining calls is an hour spent confirming the quota is still gone.

**Use a production key for full runs.** Budget roughly $3 of Cohere spend for the six-model
grid plus the Cohere judge, and about $2 of Anthropic spend for the Haiku baseline and the
Sonnet judge.

Rate limits are applied **per model**, because that is how Cohere enforces them — the 429
body reads "past the per-minute request limit for this model". So `CLARION_EVAL_COHERE_RPM=30`
means 30/min *each* for five Cohere models, ~150/min in aggregate. Generation jobs are
interleaved across models for the same reason: running one model to completion before
starting the next would point every worker at a single model's budget and stall there.

### Re-judging without regenerating

```bash
python -m clarion_eval.run --rejudge runs/<timestamp>
```

Generation is the expensive half — 1,260 requests and real money. Judging is a tenth of
that, and it is where the fixable mistakes live: a wrong judge model ID, a token budget too
small for the number of candidates, a rubric that needed sharpening. `--rejudge` re-runs
judging over an existing run's `generations.jsonl` and rewrites `judgements.jsonl` and
`REPORT.md` in place, so fixing a judging problem does not mean paying for every generation
a second time.

Note that `JUDGE_MAX_TOKENS` scales with how many models are in the grid: one score object
per candidate has to fit in a single response. 2048 was ample for four candidates and
truncated mid-JSON on six. A truncated verdict is a *lost* verdict, so the budget is set
generously and the parser salvages whole entries from a response that was cut off, rather
than discarding the candidates that did arrive.

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
- **Who wrote a row and who checked it are separate facts.** Every utterance carries
  `author` (`native` | `llm_drafted`) *and* `review_status` (`native_reviewed` |
  `unreviewed`). These were one boolean once; splitting them is what lets a
  six-language dataset stay honest. The maintainer is a native Persian speaker and can
  legitimately sign off on the Persian rows, but cannot personally vouch for the
  Chinese, Russian, Arabic, Spanish or French ones. Collapsing "nobody has checked
  this" into "reviewed: true" would let the report claim a review that never happened.
- **Publishability is per language, not per dataset.** A language is publishable only
  when every one of its rows is `native_reviewed`. Today that is Persian and nothing
  else; the report says so in a table and banners the rest.
- **The dataset validates itself.** Every listed identifier must actually appear in the
  utterance text, or loading fails — otherwise recall would be measuring nothing. Every
  row must also contain detectable text in the language it claims, so a mislabelled or
  accidentally English-only row cannot score a flawless residue number while measuring
  nothing at all.

## Limitations

State these wherever the results are cited.

- **n = 35 per language.** This is a case study, not a benchmark. It will not resolve
  small differences between strong models, and per-language cells are thinner still.
- **Only Persian is native-reviewed.** The other five languages are LLM-drafted and
  awaiting a native speaker. Their numbers are computed and reported in full, but they
  are **not publishable** and the report says so on every run. Treat them as a working
  signal, not evidence.
- **One speaker per language, at most.** The Persian rows were written by a single
  native speaker; nothing here generalises to other speakers of the same language.
- **Author-corrected synthetic.** Persian utterances were drafted programmatically and
  then rewritten by a native speaker for naturalness. The other five are drafts that
  have not had that pass yet. All are modelled on real dictation but none are
  transcripts of it.
- **The Spanish and French residue metric is a heuristic.** See *The Latin-script
  problem* above. It is tested against false positives on every run, but it is not the
  proof that the script-based check is for the other four languages.
- **Regional-tuning results are correlational.** The variants differ only in regional
  tuning as far as Cohere documents, but the training data is not public. A difference
  between Earth and Water is evidence about those two artefacts, not proof about
  regional fine-tuning in general.
- **"Identical token budget" is not identical *answer* budget.** Every model gets
  `max_tokens=1024`, but reasoning models spend part of it thinking. Command A+ returns a
  `thinking` content block and bills reasoning tokens against the same budget, so its
  usable answer space is smaller than Haiku's at the same nominal setting. Measured on the
  shipped run this changes nothing — median output is 17–77 words across all six models,
  far inside the cap — but on a task with longer outputs it would silently penalise
  reasoning models, and the comparison would no longer be apples to apples.

  It is not hypothetical at judging scale: with six candidates to score, ~1,000 reasoning
  tokens left too little room under the old 2,048-token judge budget and the Cohere judge
  emitted no `text` block at all, losing 84% of its verdicts before the budget was raised.
- **Text in, text out.** Whisper is not in the loop, so ASR errors are excluded. Real
  end-to-end quality will be lower than these numbers.
- **Judge bias is mitigated, not eliminated.** Blinding and cross-vendor judging reduce
  it; they do not remove a model's affinity for its own house style.

## Why speech-to-text is not compared

Cohere ships an ASR model, `cohere-transcribe-03-2026`, which is state of the art on
English. It supports 14 languages: English, German, French, Italian, Spanish,
Portuguese, Greek, Dutch, Polish, Vietnamese, Chinese, Arabic, Japanese and Korean.

Of the six languages here it covers four — French, Spanish, Chinese and Arabic — and
misses two: **Persian and Russian**.

Persian is the one that settles it. It is the use case Clarion was built for, so a
transcription layer that cannot handle it is not a candidate however good it is
elsewhere. Whisper covers all six, and mixing engines per language would mean the
transcription quality varied by language in a way that would contaminate every
structuring number downstream. So the transcription layer stays on Whisper and this
evaluation is scoped to structuring. That is a finding, not an omission.

## Results

Full report, with the caveats that govern it: **[RESULTS.md](RESULTS.md)**.

In short, from run `20260730T195818Z` (1,260 generations, zero failures): Claude Haiku 4.5
leads on every deterministic metric; Cohere's regional-tuning claim for the Tiny Aya
variants did not hold on any of the six languages (three ties, three losses); reasoning
cost Command A+ both accuracy and 8× the latency; and only Persian is native-reviewed, so
the five other languages are reported as unverified drafts.

Regenerating this file:

```bash
python -m clarion_eval.run                     # or --langs fa for the publishable subset
git add -f runs/<timestamp>                    # runs/ is gitignored; publishable ones are added deliberately
```

`RESULTS.md` is hand-written narrative over the generated `runs/<timestamp>/REPORT.md` —
the report is the source of the numbers, and any claim in `RESULTS.md` should be traceable
to it.
