# Results

Run `20260730T195818Z` — 6 models × 210 utterances × 6 languages, 1,260 generations,
**zero failures**. Raw generations, judgements and manifest are committed at
[`runs/20260730T195818Z-full-6lang/`](runs/20260730T195818Z-full-6lang/); every number
below is recomputable from them.

> **Only Persian is publishable.** Its 35 utterances were written and reviewed by a native
> speaker. The other five languages — Arabic, Chinese, Russian, Spanish, French — are
> LLM-drafted and `unreviewed`. Their numbers are a working signal, not evidence, and are
> marked **not publishable** in every table until a native speaker signs off. The
> cross-language findings below are stated as provisional for that reason.

## Findings

**1. The shipping default wins outright.** Claude Haiku 4.5 leads on identifier recall
(96.3%), is the only model with perfect residue and format compliance across all six
languages, and is the fastest (1,025 ms median). There is no result here that argues for
changing Clarion's default.

**2. Cohere's regional tuning claim does not hold on this task.** The Tiny Aya variants
are the same 3.35B model over the same 70 languages, differing only in which region they
were tuned toward — which makes this a controlled experiment with dataset, prompt and
decoding held fixed. Across all six languages, the variant Cohere documents as covering
the language **won zero times**: three ties and three losses. Water lost on three of the
four languages it claims, and Global — the variant with no regional tuning at all — leads
on Spanish and Chinese.

| Language | Claimed variant | Earth | Water | Global | Claim holds |
|---|---|---|---|---|---|
| Arabic | Earth | 89.5% | 85.7% | 86.7% | tied |
| Persian | Earth | 88.6% | 88.6% | 88.6% | tied |
| Russian | Water | 94.3% | 94.3% | 91.4% | tied |
| Spanish | Water | 82.9% | 85.7% | **88.6%** | **no** — Global leads |
| French | Water | **86.2%** | 83.3% | 84.3% | **no** — Earth leads |
| Chinese | Water | 86.7% | 87.1% | **88.6%** | **no** — Global leads |

This is a negative result about a published claim, and it is reported because a negative
result a reader can verify is worth more than a favourable one they cannot. Two honest
qualifications: the three "no" verdicts turn on gaps of 2–6 points on 35 utterances each,
which is not a wide margin; and five of the six languages are not yet native-reviewed. The
three ties are the more robust half of the finding.

**3. Reasoning did not pay for itself.** Command A+ finished last on identifier recall
(86.9%), last on residue (94.8%), lowest on judged fidelity (3.60), and took 8.3× Haiku's
median latency. Its `thinking` blocks draw from the same `max_tokens` budget every model
was given, which is a real cost on a task where the correct output is short.

**4. Translation tuning helps here.** Command A Translate was the open question — this
task demands translation *and* that code identifiers survive **un**translated, and those
two pressures need not point the same way. They do: 93.2% recall with perfect residue and
format, second only to Haiku.

**5. A 3.35B model is closer than its size suggests.** The Tiny Aya variants land 8 points
behind Haiku on recall while matching it on format and coming within ~2 points on residue,
at comparable latency. Not good enough to ship as the default, but the gap is small enough
that on-device structuring is worth revisiting.

## Deterministic metrics

No model in the loop. These carry the headline claims.

| Model | Completed | Identifier recall | Fully English | Format clean | Median latency |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | 210/210 | 96.3% | 100.0% | 100.0% | 1025 ms |
| Command A Translate | 210/210 | 93.2% | 100.0% | 100.0% | 3381 ms |
| Tiny Aya Earth (hosted) | 210/210 | 88.0% | 97.1% | 100.0% | 1014 ms |
| Tiny Aya Global (hosted) | 210/210 | 88.0% | 98.6% | 100.0% | 1267 ms |
| Tiny Aya Water (hosted) | 210/210 | 87.5% | 98.1% | 100.0% | 1143 ms |
| Command A+ | 210/210 | 86.9% | 94.8% | 100.0% | 8539 ms |

*Identifier recall* — share of technical tokens the speaker said that survived verbatim,
case-sensitive and token-boundary aware. *Fully English* — no source-language text left in
the output; exact by Unicode script for Persian, Arabic, Chinese and Russian, and
heuristic by function-word detection for Spanish and French, which share the Latin
alphabet with English. *Format clean* — no preamble or trailing commentary, which the
shared prompt forbids. Averages are over all 210 utterances; a failed generation counts as
zero.

## Judged metrics (blind)

Candidates were shuffled and relabelled per utterance; judges never saw model names. One
judge per vendor, because Anthropic is in the comparison and judging solely with an
Anthropic model would be a conflict.

| Model | anthropic fidelity | anthropic quality | cohere fidelity | cohere quality |
|---|---|---|---|---|
| Claude Haiku 4.5 | 4.91 | 4.45 | 4.88 | 4.38 |
| Command A Translate | 4.94 | 4.34 | 4.90 | 4.32 |
| Tiny Aya Water (hosted) | 3.65 | 3.70 | 4.28 | 4.61 |
| Command A+ | 3.60 | 3.48 | 3.99 | 4.01 |
| Tiny Aya Earth (hosted) | 3.54 | 3.61 | 4.15 | 4.51 |
| Tiny Aya Global (hosted) | 3.08 | 3.52 | 3.74 | 4.74 |

Judged pairs: `judge-anthropic` 1260/1260, `judge-cohere` 1139/1260.

**Judge agreement — 0.61 points** mean absolute difference on per-model quality averages,
on a 1–5 scale. That is large. The two judges agree closely on the top two models and
disagree substantially on the Tiny Aya variants, with the Cohere judge scoring them about
a point higher than the Anthropic judge does. **Treat every judged column as weak
evidence**; the deterministic metrics above are what the findings rest on.

## What is not measured here

- **Transcription.** The harness feeds written code-switched text directly to the
  structuring layer. Whisper's error rate on accented, code-switched speech is a real part
  of the user-visible quality and is not captured.
- **Project context.** Runs are deliberately context-free, so scores reflect multilingual
  structuring rather than retrieval over one repository.
- **Identical token budgets are not identical answer budgets.** Every model got
  `max_tokens=1024`, but reasoning models spend part of that thinking. It changed nothing
  here — median outputs ran 17–77 words, far inside the cap — but it would bite on longer
  outputs.
- **Sample size.** 35 utterances per language. Differences of a few points are not
  separable from noise.

## Reproducing

```bash
cd eval
source .venv/bin/activate

python -m clarion_eval.run --langs fa          # Persian only — the publishable subset
python -m clarion_eval.run                     # all six languages
python -m clarion_eval.run --rejudge runs/<timestamp>   # re-judge without re-generating
```

Requires `ANTHROPIC_API_KEY` and `COHERE_API_KEY`. Cohere enforces rate limits **per
model**; the harness paces itself per model and interleaves jobs across them. A full
six-language judged run is ~1,680 requests.

Methodology, metric definitions — including why Spanish and French residue is measured
differently from the other four languages — and the full limitations are in
[README.md](README.md).
