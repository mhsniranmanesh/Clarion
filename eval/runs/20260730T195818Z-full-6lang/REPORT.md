# Evaluation run `20260730T195818Z`

210 utterances across 6 languages (35 native-speaker reviewed) x 6 models. temperature=0.3, max_tokens=1024.

System prompt SHA-256 `34edc2fe2fe1bc09…` — identical to the prompt compiled into the shipping app.

> **Not publishable for Arabic, Spanish, French, Russian, Chinese.** Review status is tracked per language; only languages at 100% native-speaker review below carry publishable numbers. The rest are unverified drafts.

## Dataset

| Language | Utterances | Native-reviewed | Authored by | Residue check | Publishable |
|---|---|---|---|---|---|
| Arabic (`ar`) | 35 | 0/35 | 0/35 native, rest LLM-drafted | exact (script) | **no** |
| Spanish (`es`) | 35 | 0/35 | 0/35 native, rest LLM-drafted | heuristic (function words) | **no** |
| Persian (`fa`) | 35 | 35/35 | native speaker | exact (script) | yes |
| French (`fr`) | 35 | 0/35 | 0/35 native, rest LLM-drafted | heuristic (function words) | **no** |
| Russian (`ru`) | 35 | 0/35 | 0/35 native, rest LLM-drafted | exact (script) | **no** |
| Chinese (`zh`) | 35 | 0/35 | 0/35 native, rest LLM-drafted | exact (script) | **no** |

## Deterministic metrics

Computed from the run files with no model in the loop. These carry the headline claims.

| Model | Completed | Identifier recall | Fully English | Format clean | Median latency |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | 210/210 | 96.3% | 100.0% | 100.0% | 1025 ms |
| Command A+ | 210/210 | 86.9% | 94.8% | 100.0% | 8539 ms |
| Command A Translate | 210/210 | 93.2% | 100.0% | 100.0% | 3381 ms |
| Tiny Aya Earth (hosted) | 210/210 | 88.0% | 97.1% | 100.0% | 1014 ms |
| Tiny Aya Water (hosted) | 210/210 | 87.5% | 98.1% | 100.0% | 1143 ms |
| Tiny Aya Global (hosted) | 210/210 | 88.0% | 98.6% | 100.0% | 1267 ms |

*Identifier recall* — share of technical tokens the speaker said that survived verbatim, case-sensitive, token-boundary aware. *Fully English* — no source-language text left in the output; measured exactly by Unicode script for Persian, Arabic, Chinese and Russian, and heuristically by function-word detection for Spanish and French, which share the Latin alphabet with English. *Format clean* — no preamble or trailing commentary, which the shared prompt forbids. Averages are over all 210 utterances; a failed generation counts as zero.

### By language

The same three deterministic metrics, split by source language. This is where a model that is strong on one language and weak on another stops being hidden by the average above.

**Identifier recall**

| Model | Arabic | Spanish | Persian | French | Russian | Chinese |
|---|---|---|---|---|---|---|
| Claude Haiku 4.5 | 94.8% | 94.3% | 98.6% | 95.7% | 97.1% | 97.6% |
| Command A+ | 94.3% | 74.3% | 100.0% | 81.4% | 82.9% | 88.6% |
| Command A Translate | 90.0% | 92.9% | 95.7% | 94.3% | 94.3% | 91.9% |
| Tiny Aya Earth (hosted) | 89.5% | 82.9% | 88.6% | 86.2% | 94.3% | 86.7% |
| Tiny Aya Water (hosted) | 85.7% | 85.7% | 88.6% | 83.3% | 94.3% | 87.1% |
| Tiny Aya Global (hosted) | 86.7% | 88.6% | 88.6% | 84.3% | 91.4% | 88.6% |

**Fully English**

| Model | Arabic | Spanish | Persian | French | Russian | Chinese |
|---|---|---|---|---|---|---|
| Claude Haiku 4.5 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Command A+ | 100.0% | 97.1% | 97.1% | 88.6% | 97.1% | 88.6% |
| Command A Translate | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Tiny Aya Earth (hosted) | 94.3% | 100.0% | 100.0% | 97.1% | 97.1% | 94.3% |
| Tiny Aya Water (hosted) | 97.1% | 97.1% | 100.0% | 97.1% | 100.0% | 97.1% |
| Tiny Aya Global (hosted) | 97.1% | 100.0% | 97.1% | 97.1% | 100.0% | 100.0% |

**Format clean**

| Model | Arabic | Spanish | Persian | French | Russian | Chinese |
|---|---|---|---|---|---|---|
| Claude Haiku 4.5 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Command A+ | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Command A Translate | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Tiny Aya Earth (hosted) | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Tiny Aya Water (hosted) | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Tiny Aya Global (hosted) | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

### Regional tuning

The Tiny Aya variants are the same 3.35B model over the same 70 languages, differing only in which region's languages they were tuned toward. Holding the dataset, prompt and decoding fixed, any difference between these rows is attributable to the regional tuning alone. Cohere's model cards claim Earth covers Persian and Arabic, and Water covers Chinese, Russian, Spanish and French.

| Language | Claimed variant | Tiny Aya Earth (hosted) | Tiny Aya Water (hosted) | Tiny Aya Global (hosted) | Claim holds |
|---|---|---|---|---|---|
| Arabic | Tiny Aya Earth (hosted) | 89.5% | 85.7% | 86.7% | tied |
| Spanish | Tiny Aya Water (hosted) | 82.9% | 85.7% | 88.6% | **no** — Tiny Aya Global (hosted) leads |
| Persian | Tiny Aya Earth (hosted) | 88.6% | 88.6% | 88.6% | tied |
| French | Tiny Aya Water (hosted) | 86.2% | 83.3% | 84.3% | **no** — Tiny Aya Earth (hosted) leads |
| Russian | Tiny Aya Water (hosted) | 94.3% | 94.3% | 91.4% | tied |
| Chinese | Tiny Aya Water (hosted) | 86.7% | 87.1% | 88.6% | **no** — Tiny Aya Global (hosted) leads |

Compared on identifier recall, the metric that is exact for every language in the set. A claim marked **no** means the region-matched variant did not lead on the language it is documented to cover.

## Judged metrics (blind)

Candidates were shuffled and relabelled per utterance; judges never saw model names. Judges: `judge-anthropic`, `judge-cohere`.

| Model | judge-anthropic fidelity | judge-anthropic quality | judge-cohere fidelity | judge-cohere quality |
|---|---|---|---|---|
| Claude Haiku 4.5 | 4.91 | 4.45 | 4.88 | 4.38 |
| Command A+ | 3.60 | 3.48 | 3.99 | 4.01 |
| Command A Translate | 4.94 | 4.34 | 4.90 | 4.32 |
| Tiny Aya Earth (hosted) | 3.54 | 3.61 | 4.15 | 4.51 |
| Tiny Aya Water (hosted) | 3.65 | 3.70 | 4.28 | 4.61 |
| Tiny Aya Global (hosted) | 3.08 | 3.52 | 3.74 | 4.74 |

Judged pairs per judge: `judge-anthropic`=1260, `judge-cohere`=1139 (expected 1260 each).

**Judge agreement** — mean absolute difference between `judge-anthropic` and `judge-cohere` on per-model quality averages: 0.61 points on a 1–5 scale. Large values mean the judged numbers should be treated as weak evidence.

---

Raw generations, judgements and the run manifest are committed next to this report. Every number above is recomputable from them.
