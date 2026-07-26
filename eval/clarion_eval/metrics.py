"""Deterministic metrics.

These carry the headline claims. They are pure functions of (input, output) with
no model in the loop, so anyone can recompute them from the committed run files
and get byte-identical numbers.

The LLM-judged scores in `judge.py` are reported alongside, but deliberately as
secondary evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

# ── Identifier preservation ──────────────────────────────────────────────────

_WORD = "A-Za-z0-9_"


def _occurs(identifier: str, text: str, *, fold_case: bool = False) -> bool:
    """True if `identifier` appears in `text` as a standalone token.

    Boundary-aware so `useState` matches in `useState()`, `` `useState` `` and
    "the useState hook", but not inside `myUseStateThing`. Dotted and
    snake_cased identifiers work because the identifier is escaped literally.
    """
    flags = re.IGNORECASE if fold_case else 0
    pattern = re.compile(
        rf"(?<![{_WORD}]){re.escape(identifier)}(?![{_WORD}])", flags
    )
    return bool(pattern.search(text))


@dataclass
class IdentifierScore:
    total: int
    preserved: int
    preserved_case_insensitive: int
    missing: list[str]
    case_only_errors: list[str]

    @property
    def recall(self) -> float:
        return self.preserved / self.total if self.total else 1.0

    @property
    def recall_case_insensitive(self) -> float:
        return (
            self.preserved_case_insensitive / self.total if self.total else 1.0
        )


def score_identifiers(identifiers: list[str], output: str) -> IdentifierScore:
    """Exact-match recall of technical tokens that must survive translation.

    Case-sensitive recall is the reported metric, because `useState` and
    `usestate` are different symbols to a compiler. Case-insensitive recall is
    tracked too, so a model that kept the word but mangled the casing is
    distinguishable from one that dropped it entirely.
    """
    missing: list[str] = []
    case_only: list[str] = []
    preserved = 0
    preserved_ci = 0

    for ident in identifiers:
        exact = _occurs(ident, output)
        loose = _occurs(ident, output, fold_case=True)
        if exact:
            preserved += 1
        if loose:
            preserved_ci += 1
        if not exact:
            (case_only if loose else missing).append(ident)

    return IdentifierScore(
        total=len(identifiers),
        preserved=preserved,
        preserved_case_insensitive=preserved_ci,
        missing=missing,
        case_only_errors=case_only,
    )


# ── Residual non-English script ──────────────────────────────────────────────

# Persian is written in Arabic script. Any codepoint from these blocks surviving
# into the output means the model failed to translate that span.
_ARABIC_BLOCKS = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Presentation Forms-A
    (0xFE70, 0xFEFF),  # Presentation Forms-B
)


def _is_arabic_script(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _ARABIC_BLOCKS)


@dataclass
class ScriptScore:
    residual_chars: int
    residual_sample: str

    @property
    def fully_english(self) -> bool:
        return self.residual_chars == 0


def score_script(output: str) -> ScriptScore:
    """Counts Persian/Arabic-script characters left in the English output.

    Unambiguous and binary in practice: a correct answer has zero.
    """
    residual = [ch for ch in output if _is_arabic_script(ch)]
    sample = "".join(residual[:60])
    return ScriptScore(residual_chars=len(residual), residual_sample=sample)


# ── Format compliance ────────────────────────────────────────────────────────

# Deliberately conservative. A structured prompt legitimately often begins "I
# want..." or "I have a bug where...", so first-person openings are NOT flagged.
# Only unambiguous meta-commentary counts as a violation.
_PREAMBLE_PATTERNS = [
    (r"^\s*here(?:'s| is| are)\s+(?:the|your|a|an)\b", "leading_here_is"),
    (r"^\s*(?:sure|certainly|of course|okay|alright)\s*[,.!:]", "leading_filler"),
    (r"^\s*below is\b", "leading_below_is"),
    (r"^\s*structured\s+(?:english\s+)?prompt\s*:", "echoes_label"),
    (r"^\s*```", "wrapped_in_code_fence"),
]

_TRAILING_PATTERNS = [
    (r"\blet me know if\b", "trailing_offer"),
    (r"\bhope this helps\b", "trailing_offer"),
    (r"\bwould you like me to\b", "trailing_offer"),
]


@dataclass
class FormatScore:
    violations: list[str]

    @property
    def clean(self) -> bool:
        return not self.violations


def score_format(output: str) -> FormatScore:
    """Detects preamble and commentary the shared prompt explicitly forbids.

    Reported separately from quality so that a model losing points purely for a
    formatting tic is visible as such, rather than being silently marked down as
    a worse translator.
    """
    violations: list[str] = []
    for pattern, name in _PREAMBLE_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            violations.append(name)
    for pattern, name in _TRAILING_PATTERNS:
        if re.search(pattern, output, re.IGNORECASE):
            violations.append(name)
    return FormatScore(violations=sorted(set(violations)))


# ── Length ───────────────────────────────────────────────────────────────────


def _word_count(text: str) -> int:
    return len([t for t in re.split(r"\s+", text.strip()) if t])


def length_ratio(output: str, reference: str) -> float:
    """Output length over reference-gloss length. Catches truncation (<<1) and
    padding (>>1); neither is penalised directly, it is a diagnostic."""
    ref = _word_count(reference)
    return _word_count(output) / ref if ref else 0.0


# ── Aggregate ────────────────────────────────────────────────────────────────


@dataclass
class DeterministicScores:
    identifiers: IdentifierScore
    script: ScriptScore
    fmt: FormatScore
    length_ratio: float
    empty_output: bool

    def to_dict(self) -> dict:
        return {
            "identifier_recall": round(self.identifiers.recall, 4),
            "identifier_recall_ci": round(
                self.identifiers.recall_case_insensitive, 4
            ),
            "identifiers_total": self.identifiers.total,
            "identifiers_preserved": self.identifiers.preserved,
            "identifiers_missing": self.identifiers.missing,
            "identifiers_case_only_errors": self.identifiers.case_only_errors,
            "residual_persian_chars": self.script.residual_chars,
            "residual_persian_sample": self.script.residual_sample,
            "fully_english": self.script.fully_english,
            "format_clean": self.fmt.clean,
            "format_violations": self.fmt.violations,
            "length_ratio": round(self.length_ratio, 3),
            "empty_output": self.empty_output,
        }


def score_all(output: str, identifiers: list[str], gloss: str) -> DeterministicScores:
    normalised = unicodedata.normalize("NFC", output or "")
    return DeterministicScores(
        identifiers=score_identifiers(identifiers, normalised),
        script=score_script(normalised),
        fmt=score_format(normalised),
        length_ratio=length_ratio(normalised, gloss),
        empty_output=not normalised.strip(),
    )


__all__ = [
    "DeterministicScores",
    "FormatScore",
    "IdentifierScore",
    "ScriptScore",
    "asdict",
    "score_all",
    "score_format",
    "score_identifiers",
    "score_script",
]
