"""Model registry for the evaluation.

Every entry names a concrete, published model. `kind` selects the client in
`providers.py`. Adding a model here is the only step needed to include it in a
run.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    key: str
    """Short identifier used in CLI flags, filenames and report columns."""

    api_name: str
    """The exact model ID sent to the provider."""

    kind: str
    """One of: anthropic, cohere, local_gguf."""

    label: str
    """Human-readable name for the report."""

    params: str = ""
    """Parameter count, when publicly known. Blank for closed models."""

    notes: str = ""

    extra: dict = field(default_factory=dict)


REGISTRY: dict[str, ModelSpec] = {
    # ── Baseline ─────────────────────────────────────────────────────────────
    "haiku": ModelSpec(
        key="haiku",
        api_name="claude-haiku-4-5-20251001",
        kind="anthropic",
        label="Claude Haiku 4.5",
        notes="Clarion's shipping default. The baseline every other model is measured against.",
    ),
    # ── Cohere hosted ────────────────────────────────────────────────────────
    "command-a-plus": ModelSpec(
        key="command-a-plus",
        api_name="command-a-plus-05-2026",
        kind="cohere",
        label="Command A+",
        notes="Cohere's current flagship. The like-for-like quality comparison.",
    ),
    "command-a-translate": ModelSpec(
        key="command-a-translate",
        api_name="command-a-translate-08-2025",
        kind="cohere",
        label="Command A Translate",
        notes="Translation-specialised. Tests whether translation tuning helps or hurts "
        "when the task also requires preserving code identifiers verbatim.",
    ),
    "tiny-aya-earth": ModelSpec(
        key="tiny-aya-earth",
        api_name="tiny-aya-earth",
        kind="cohere",
        label="Tiny Aya Earth (hosted)",
        params="3.35B",
        notes="Regional variant tuned for West Asian and African languages, which is where "
        "Persian sits. The headline result of this evaluation.",
    ),
    "tiny-aya-global": ModelSpec(
        key="tiny-aya-global",
        api_name="tiny-aya-global",
        kind="cohere",
        label="Tiny Aya Global (hosted)",
        params="3.35B",
        notes="Balanced multilingual variant. Included to isolate whether the Earth "
        "regional tuning actually helps Persian.",
    ),
    # ── Cohere local ─────────────────────────────────────────────────────────
    # Requires a downloaded GGUF; see eval/README.md. Path is supplied at runtime
    # via --gguf-path, so no filename is hardcoded here.
    "tiny-aya-earth-local": ModelSpec(
        key="tiny-aya-earth-local",
        api_name="tiny-aya-earth",
        kind="local_gguf",
        label="Tiny Aya Earth (local GGUF)",
        params="3.35B",
        notes="Same weights run on-device via llama.cpp. Measures whether Clarion can "
        "structure prompts fully offline, and at what quality and latency cost.",
    ),
}


DEFAULT_MODELS = [
    "haiku",
    "command-a-plus",
    "command-a-translate",
    "tiny-aya-earth",
]


def resolve(keys: list[str]) -> list[ModelSpec]:
    unknown = [k for k in keys if k not in REGISTRY]
    if unknown:
        raise SystemExit(
            f"Unknown model key(s): {', '.join(unknown)}\n"
            f"Available: {', '.join(REGISTRY)}"
        )
    return [REGISTRY[k] for k in keys]
