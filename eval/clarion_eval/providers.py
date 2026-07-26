"""Provider clients.

`complete()` sends the *same* system prompt, user message, temperature and token
budget to every model — the ones the Clarion app itself uses, read from
`prompts/structure_system.txt`. Any difference between models in the results is
therefore a difference in the model, not in how it was asked.

`chat()` is the generic escape hatch, used by the judge.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .models import ModelSpec

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO_ROOT / "prompts" / "structure_system.txt"

# Must match src-tauri/src/structure/mod.rs. Enforced by tests/test_parity.py.
TEMPERATURE = 0.3
MAX_TOKENS = 1024

REQUEST_TIMEOUT = 180


def system_prompt() -> str:
    """The exact prompt the shipping app uses, with no project context.

    The evaluation deliberately runs without project context so scores reflect
    multilingual structuring ability rather than retrieval over one repository.
    """
    return PROMPT_PATH.read_text(encoding="utf-8").rstrip()


def user_message(raw_text: str) -> str:
    return f'Raw voice transcription:\n\n"{raw_text}"\n\nStructured English prompt:'


@dataclass
class Completion:
    text: str
    latency_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class ProviderError(RuntimeError):
    pass


# ── Anthropic ────────────────────────────────────────────────────────────────


def _anthropic(
    api_name: str, system: str, user: str, temperature: float, max_tokens: int
) -> Completion:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return Completion("", 0, error="ANTHROPIC_API_KEY is not set")

    started = time.monotonic()
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": api_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return Completion("", _ms(started), error=str(exc))

    if resp.status_code != 200:
        return Completion(
            "", _ms(started), error=f"HTTP {resp.status_code}: {resp.text[:400]}"
        )

    blocks = resp.json().get("content", [])
    text = next((b.get("text", "") for b in blocks if b.get("type") == "text"), "")
    return Completion(text.strip(), _ms(started))


# ── Cohere ───────────────────────────────────────────────────────────────────


def _cohere(
    api_name: str, system: str, user: str, temperature: float, max_tokens: int
) -> Completion:
    key = os.environ.get("COHERE_API_KEY", "").strip()
    if not key:
        return Completion("", 0, error="COHERE_API_KEY is not set")

    started = time.monotonic()
    try:
        resp = requests.post(
            "https://api.cohere.com/v2/chat",
            headers={
                "Authorization": f"Bearer {key}",
                "content-type": "application/json",
            },
            json={
                "model": api_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return Completion("", _ms(started), error=str(exc))

    if resp.status_code != 200:
        return Completion(
            "", _ms(started), error=f"HTTP {resp.status_code}: {resp.text[:400]}"
        )

    blocks = resp.json().get("message", {}).get("content", [])
    text = next((b.get("text", "") for b in blocks if b.get("type") == "text"), "")
    return Completion(text.strip(), _ms(started))


# ── Local GGUF (llama.cpp) ───────────────────────────────────────────────────

_LLAMA_CACHE: dict[str, object] = {}


def _get_llama(gguf_path: str, n_ctx: int = 8192):
    """Loads and caches a llama.cpp model. The import is deferred so the
    API-only path never requires llama-cpp-python."""
    if gguf_path in _LLAMA_CACHE:
        return _LLAMA_CACHE[gguf_path]

    try:
        from llama_cpp import Llama
    except ImportError as exc:  # pragma: no cover - optional extra
        raise ProviderError(
            "llama-cpp-python is not installed. Install the local extra:\n"
            "    pip install -e '.[local]'"
        ) from exc

    if not Path(gguf_path).exists():
        raise ProviderError(f"GGUF file not found: {gguf_path}")

    model = Llama(
        model_path=gguf_path,
        n_ctx=n_ctx,
        n_gpu_layers=-1,  # offload to Metal on Apple silicon
        verbose=False,
    )
    _LLAMA_CACHE[gguf_path] = model
    return model


def _local_gguf(
    gguf_path: str | None,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
) -> Completion:
    if not gguf_path:
        return Completion("", 0, error="--gguf-path is required for local models")

    started = time.monotonic()
    try:
        model = _get_llama(gguf_path)
        result = model.create_chat_completion(  # type: ignore[attr-defined]
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001 - always report, never silently drop
        return Completion("", _ms(started), error=str(exc))

    text = result["choices"][0]["message"]["content"] or ""
    return Completion(text.strip(), _ms(started))


# ── Dispatch ─────────────────────────────────────────────────────────────────


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def chat(
    kind: str,
    api_name: str,
    system: str,
    user: str,
    *,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    gguf_path: str | None = None,
) -> Completion:
    """Generic single-turn chat against any supported backend."""
    if kind == "anthropic":
        return _anthropic(api_name, system, user, temperature, max_tokens)
    if kind == "cohere":
        return _cohere(api_name, system, user, temperature, max_tokens)
    if kind == "local_gguf":
        return _local_gguf(gguf_path, system, user, temperature, max_tokens)
    return Completion("", 0, error=f"Unknown provider kind: {kind}")


def complete(spec: ModelSpec, raw_text: str, gguf_path: str | None = None) -> Completion:
    """Runs the structuring task exactly as the app runs it."""
    return chat(
        spec.kind,
        spec.api_name,
        system_prompt(),
        user_message(raw_text),
        gguf_path=gguf_path,
    )
