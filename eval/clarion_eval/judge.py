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

from .providers import chat

JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 2048

JUDGE_SYSTEM = """\
You are grading how well different systems converted one spoken, code-switched \
utterance from a software developer into an English prompt for an AI coding \
assistant. The speaker mixes Persian with English technical terms.

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

Respond with ONLY a JSON object, no prose and no code fence:
{"scores": {"A": {"fidelity": 4, "quality": 5, "note": "brief reason"}, ...}}
"""


@dataclass(frozen=True)
class JudgeSpec:
    key: str
    kind: str
    api_name: str
    label: str


# One judge per vendor. Override with --judge if either ID is unavailable on
# your account; the run records whichever judges actually answered.
DEFAULT_JUDGES = [
    JudgeSpec("judge-anthropic", "anthropic", "claude-sonnet-4-6-20250514", "Claude Sonnet 4.6"),
    JudgeSpec("judge-cohere", "cohere", "command-a-plus-05-2026", "Command A+"),
]


def _build_user_message(
    utterance: str, gloss: str, labelled: dict[str, str]
) -> str:
    parts = [
        "Original utterance (code-switched Persian/English):",
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


def _extract_json(raw: str) -> dict | None:
    """Judges occasionally wrap JSON in a fence despite instructions."""
    candidate = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None


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
        JUDGE_SYSTEM,
        _build_user_message(utterance, gloss, labelled),
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
