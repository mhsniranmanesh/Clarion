"""Blind LLM judging for the two qualities no regex can measure: whether the
translation preserved meaning, and whether the result is a good coding-agent
prompt.

Three deliberate choices, because judged scores are the softest evidence here:

1. **Blind.** The judge never sees model names. Candidates are shuffled and
   relabelled A/B/C/... per utterance.
2. **Deterministic shuffle.** The permutation is seeded from the utterance id,
   so a rerun produces the same layout and results stay reproducible.
3. **Two judges from different vendors.** Anthropic is in the comparison, so
   judging solely with an Anthropic model would be a conflict. Running one judge
   from each vendor and reporting agreement makes any vendor affinity visible
   instead of hidden.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from . import languages
from .providers import chat

JUDGE_TEMPERATURE = 0.0

# Sized for the whole grid, not one comparison. The budget has to cover a score
# object per candidate, so it scales with how many models are in the run — 2048
# was ample for four candidates and truncated mid-JSON on six whenever the judge
# wrote detailed notes. A truncated response is a *lost verdict*, not a bad one,
# so this is bought cheaply: unused budget costs nothing.
JUDGE_MAX_TOKENS = 4096

JUDGE_SYSTEM_TEMPLATE = """\
You are grading how well different systems converted one spoken, code-switched \
utterance from a software developer into an English prompt for an AI coding \
assistant. The speaker mixes {language} with English technical terms.

You will be given the original utterance, a reference gloss of what the speaker \
meant, and several candidate outputs labelled A, B, C, ...

Score every candidate on two independent axes, each an integer from 1 to 5.

fidelity — did it preserve the speaker's meaning?
  5: every element of intent preserved; nothing invented, nothing dropped
  4: intent preserved; a minor nuance softened
  3: main request survives but a meaningful detail is lost or altered
  2: partially wrong, or invents requirements the speaker never stated
  1: unrelated, empty, or contradicts the speaker

quality — is it a good prompt to hand to a coding assistant?
  5: clear, specific, well-organised, immediately actionable
  4: clear and usable, slightly loose structure
  3: understandable but vague or rambling
  2: hard to act on
  1: unusable

Judge only these two axes. Do not reward or punish length, formatting, or the \
presence of a preamble — those are measured separately.

Keep each note under 15 words. Long notes push the response past its token \
budget and the whole verdict is lost, including the scores.

Respond with ONLY a JSON object, no prose and no code fence:
{{"scores": {{"A": {{"fidelity": 4, "quality": 5, "note": "brief reason"}}, ...}}}}
"""


def judge_system(lang: str) -> str:
    """The grading rubric, named for the language actually being judged.

    A judge told the input is Persian while reading Mandarin has been handed a
    reason to mark every candidate down.
    """
    return JUDGE_SYSTEM_TEMPLATE.format(language=languages.get(lang).name)


@dataclass(frozen=True)
class JudgeSpec:
    key: str
    kind: str
    api_name: str
    label: str


# One judge per vendor. Override with --judge if either ID is unavailable on
# your account; the run records whichever judges actually answered.
DEFAULT_JUDGES = [
    JudgeSpec("judge-anthropic", "anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
    JudgeSpec("judge-cohere", "cohere", "command-a-plus-05-2026", "Command A+"),
]


def _build_user_message(
    utterance: str, gloss: str, labelled: dict[str, str], lang: str
) -> str:
    language = languages.get(lang)
    parts = [
        f"Original utterance (code-switched {language.name}/English):",
        utterance,
        "",
        "Reference gloss of the speaker's intent (written by a native speaker):",
        gloss,
        "",
        "Candidates:",
    ]
    for label in sorted(labelled):
        text = labelled[label].strip() or "(empty output)"
        parts += ["", f"--- {label} ---", text]
    parts += ["", "Return the JSON object now."]
    return "\n".join(parts)


# One complete `"A": {...}` entry. Used to salvage a response that was cut off
# partway through, where the entries that did arrive are still perfectly good.
_SCORE_ENTRY = re.compile(r'"([A-Za-z])"\s*:\s*(\{[^{}]*\})')


def _salvage_scores(raw: str) -> dict | None:
    """Recovers whole candidate entries from a response that failed to parse.

    A verdict truncated mid-JSON is not a wrong answer, it is a partial one —
    the candidates already emitted were scored correctly. Discarding all of them
    because the last one was cut off throws away good data and, worse, does it
    unevenly: the judge writes candidates in label order, so the loss always
    falls on the same labels. Salvaging keeps whatever survived, and the
    caller's existing `judge omitted: ...` path records the rest as missing.
    """
    scores = {}
    for label, blob in _SCORE_ENTRY.findall(raw):
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if "fidelity" in payload and "quality" in payload:
            scores[label] = payload
    return {"scores": scores} if scores else None


def _extract_json(raw: str) -> dict | None:
    """Judges occasionally wrap JSON in a fence despite instructions."""
    candidate = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    return _salvage_scores(candidate)


def blind_labels(utterance_id: str, model_keys: list[str]) -> dict[str, str]:
    """Maps label -> model_key using a permutation seeded by the utterance id."""
    shuffled = list(model_keys)
    random.Random(f"clarion::{utterance_id}").shuffle(shuffled)
    return {chr(ord("A") + i): key for i, key in enumerate(shuffled)}


def judge_utterance(
    judge: JudgeSpec,
    utterance_id: str,
    utterance: str,
    gloss: str,
    outputs: dict[str, str],
    lang: str = "fa",
) -> dict:
    """Scores one utterance's candidates. Returns {model_key: {...}} plus errors.

    A judge failure is recorded, never silently dropped — otherwise averages
    would quietly be taken over a subset that happened to succeed.
    """
    model_keys = sorted(outputs)
    label_to_model = blind_labels(utterance_id, model_keys)
    labelled = {label: outputs[key] for label, key in label_to_model.items()}

    result = chat(
        judge.kind,
        judge.api_name,
        judge_system(lang),
        _build_user_message(utterance, gloss, labelled, lang),
        temperature=JUDGE_TEMPERATURE,
        max_tokens=JUDGE_MAX_TOKENS,
    )

    if not result.ok:
        return {"error": result.error, "scores": {}}

    parsed = _extract_json(result.text)
    if not parsed or "scores" not in parsed:
        return {
            "error": f"unparseable judge response: {result.text[:300]}",
            "scores": {},
        }

    scores: dict[str, dict] = {}
    for label, payload in parsed["scores"].items():
        model_key = label_to_model.get(label.strip().upper())
        if not model_key or not isinstance(payload, dict):
            continue
        try:
            scores[model_key] = {
                "fidelity": int(payload["fidelity"]),
                "quality": int(payload["quality"]),
                "note": str(payload.get("note", ""))[:300],
            }
        except (KeyError, TypeError, ValueError):
            continue

    missing = [k for k in model_keys if k not in scores]
    return {
        "error": f"judge omitted: {', '.join(missing)}" if missing else None,
        "scores": scores,
        "label_map": label_to_model,
    }
