"""Provider clients.

`complete()` sends the *same* system prompt, user message, temperature and token
budget to every model — the ones the Clarion app itself uses, read from
`prompts/structure_system.txt`. Any difference between models in the results is
therefore a difference in the model, not in how it was asked.

`chat()` is the generic escape hatch, used by the judge.
"""

from __future__ import annotations

import os
import random
import re
import threading
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

MAX_ATTEMPTS = 6


# ── Rate limiting ────────────────────────────────────────────────────────────
#
# A full run is well over a thousand calls. Without pacing most come back 429 and
# the run reports a rate limit as if it were a model failure — which is how you
# end up publishing "Tiny Aya Water scored 0%" when the truth is that it was
# never asked.
#
# Limits are enforced **per model**, not per provider, because that is how Cohere
# enforces them: the 429 body reads "past the per-minute request limit for this
# model". A per-provider gate is the wrong shape — the runner interleaves models
# (see `_generate`), so a single account-wide budget would either throttle the
# whole run to one model's ceiling or let all workers pile onto one model and
# blow it. Per-model gates let N models run at N x the per-model rate.

_DEFAULT_RPM = {
    "anthropic": 0,  # unlimited by default; paid tiers are generous
    "cohere": 20,  # safe for trial keys; raise via CLARION_EVAL_COHERE_RPM
}


class _RateLimiter:
    """Spaces calls so a provider's requests-per-minute cap is not exceeded.

    Deliberately a simple minimum-interval gate rather than a token bucket. A
    bucket would let a burst through at the start of a run and then stall; even
    spacing keeps the latency numbers comparable across models, which is the
    whole point of the harness.
    """

    def __init__(self, rpm: int) -> None:
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.interval
        if wait:
            time.sleep(wait)


def _rpm_for(kind: str) -> int:
    """Requests per minute allowed **per model** of this provider.

    Overridable as e.g. `CLARION_EVAL_COHERE_RPM=30`.
    """
    override = os.environ.get(f"CLARION_EVAL_{kind.upper()}_RPM")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return _DEFAULT_RPM.get(kind, 0)


_LIMITERS: dict[tuple[str, str], _RateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter(kind: str, api_name: str = "") -> _RateLimiter:
    """The gate for one (provider, model) pair."""
    key = (kind, api_name)
    with _LIMITERS_LOCK:
        if key not in _LIMITERS:
            _LIMITERS[key] = _RateLimiter(_rpm_for(kind))
        return _LIMITERS[key]


def _retry_after(response: requests.Response, attempt: int) -> float:
    """How long to wait before retrying, preferring the server's own answer."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), 120.0)
        except ValueError:
            pass
    # Exponential backoff with jitter, so parallel workers do not resynchronise
    # and hit the next window together.
    return min(2.0**attempt, 60.0) * (0.5 + random.random())


# A 429 means two completely different things and only one of them is worth
# waiting for. "20 API calls / minute" clears in seconds. "1000 API calls /
# month" does not clear this month, and retrying it six times with backoff turns
# an instant failure into a 45-second one — which, across a thousand-call run,
# is an hour spent confirming the quota is still gone.
_QUOTA_EXHAUSTED = re.compile(
    r"/\s*(?:month|day)\b"  # "1000 API calls / month"
    r"|monthly limit"
    r"|quota (?:exceeded|exhausted)"
    r"|exceeded[^.]{0,40}quota"  # "exceeded your current quota"
    r"|insufficient[_ ]quota",
    re.IGNORECASE,
)


def is_quota_exhausted(body: str) -> bool:
    """True when a 429 reports a spent billing-period quota, not a rate limit."""
    return bool(_QUOTA_EXHAUSTED.search(body or ""))


def _should_retry(status: int, body: str = "") -> bool:
    if status == 429:
        return not is_quota_exhausted(body)
    return 500 <= status < 600


def _post_with_retry(
    kind: str, url: str, headers: dict, payload: dict, api_name: str = ""
) -> tuple[requests.Response | None, str | None]:
    """POSTs with rate limiting and retry. Returns (response, error).

    A retried request is not a failed one: the error is only returned once the
    attempts are exhausted, so a transient 429 does not get recorded as the model
    declining to answer.
    """
    gate = limiter(kind, api_name)
    last: str | None = None

    for attempt in range(MAX_ATTEMPTS):
        gate.acquire()
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            last = str(exc)
            if attempt == MAX_ATTEMPTS - 1:
                return None, last
            time.sleep(min(2.0**attempt, 30.0) * (0.5 + random.random()))
            continue

        if response.status_code == 200:
            return response, None

        body = response.text
        last = f"HTTP {response.status_code}: {body[:400]}"
        if not _should_retry(response.status_code, body) or attempt == MAX_ATTEMPTS - 1:
            return response, last

        time.sleep(_retry_after(response, attempt))

    return None, last


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
    resp, error = _post_with_retry(
        "anthropic",
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        {
            "model": api_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        api_name=api_name,
    )
    if error or resp is None:
        return Completion("", _ms(started), error=error or "no response")

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
    resp, error = _post_with_retry(
        "cohere",
        "https://api.cohere.com/v2/chat",
        {
            "Authorization": f"Bearer {key}",
            "content-type": "application/json",
        },
        {
            "model": api_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        api_name=api_name,
    )
    if error or resp is None:
        return Completion("", _ms(started), error=error or "no response")

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
