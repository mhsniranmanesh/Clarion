"""Tests for judging and request pacing.

Both are places where a silent bug produces numbers that look fine and are wrong:
a judge told the wrong source language marks every candidate down, and an
unpaced run turns a rate limit into what reads like model failure.

    python -m pytest eval/tests -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clarion_eval import judge, languages, models, providers, run  # noqa: E402


class TestJudgePrompt:
    @pytest.mark.parametrize("code", languages.codes())
    def test_names_the_actual_source_language(self, code):
        system = judge.judge_system(code)
        assert languages.get(code).name in system

    def test_does_not_name_a_language_it_is_not_judging(self):
        """The rubric was Persian-only once. A judge reading Mandarin while told
        the input is Persian has been handed a reason to mark everything down."""
        system = judge.judge_system("zh")
        for other in ("Persian", "Russian", "Spanish", "French", "Arabic"):
            assert other not in system

    def test_json_example_survives_template_formatting(self):
        """The rubric embeds a literal JSON example, so its braces have to be
        escaped for str.format. Getting that wrong yields a prompt that asks for
        a malformed shape, and every judgement fails to parse."""
        system = judge.judge_system("fa")
        assert '{"scores": {"A": {"fidelity": 4, "quality": 5' in system

    def test_user_message_names_the_language(self):
        message = judge._build_user_message("你好", "hello", {"A": "hi"}, "zh")
        assert "code-switched Chinese/English" in message


class TestVerdictParsing:
    CLEAN = '{"scores": {"A": {"fidelity": 4, "quality": 5, "note": "x"}}}'

    def test_plain_json(self):
        assert sorted(judge._extract_json(self.CLEAN)["scores"]) == ["A"]

    def test_code_fence_is_stripped(self):
        assert judge._extract_json(f"```json\n{self.CLEAN}\n```") is not None

    def test_prose_around_json_is_tolerated(self):
        assert judge._extract_json(f"Here you go:\n{self.CLEAN}\nHope that helps") is not None

    def test_unusable_response_is_none(self):
        assert judge._extract_json("sorry, I cannot help with that") is None

    def test_truncated_response_is_salvaged(self):
        """A verdict cut off mid-JSON is partial, not wrong. Discarding all of
        it would throw away correctly-scored candidates — and always the same
        labels, since the judge emits them in order."""
        truncated = (
            '{"scores": {"A": {"fidelity": 3, "quality": 4, "note": "ok"}, '
            '"B": {"fidelity": 5, "quality": 5, "note": "good"}, '
            '"C": {"fidelity": 2, "quality": 3, "note": "Invents context about multi'
        )
        recovered = judge._extract_json(truncated)
        assert sorted(recovered["scores"]) == ["A", "B"]
        assert recovered["scores"]["B"]["fidelity"] == 5

    def test_salvage_skips_entries_missing_required_fields(self):
        assert judge._salvage_scores('{"scores": {"A": {"note": "no scores here"}}}') is None

    def test_token_budget_scales_with_candidate_count(self):
        """2048 was ample for four candidates and truncated on six. The default
        grid is six models, so the budget has to clear that."""
        assert judge.JUDGE_MAX_TOKENS >= 4096
        assert "under 15 words" in judge.judge_system("fa")


class TestBlindLabels:
    def test_permutation_is_seeded_and_stable(self):
        first = judge.blind_labels("zh-001", ["a", "b", "c"])
        second = judge.blind_labels("zh-001", ["a", "b", "c"])
        assert first == second

    def test_different_utterances_get_different_layouts(self):
        layouts = {
            tuple(sorted(judge.blind_labels(f"fa-{i:03d}", ["a", "b", "c"]).items()))
            for i in range(20)
        }
        assert len(layouts) > 1, "labels are not being shuffled across utterances"

    def test_every_model_gets_a_label(self):
        labels = judge.blind_labels("ru-001", ["x", "y", "z"])
        assert sorted(labels) == ["A", "B", "C"]
        assert sorted(labels.values()) == ["x", "y", "z"]


class TestRateLimiter:
    def test_zero_rpm_does_not_block(self):
        gate = providers._RateLimiter(0)
        started = time.monotonic()
        for _ in range(50):
            gate.acquire()
        assert time.monotonic() - started < 0.1

    def test_calls_are_spaced(self):
        gate = providers._RateLimiter(600)  # 10/second -> 100ms apart
        started = time.monotonic()
        for _ in range(4):
            gate.acquire()
        # First call is free; the remaining three wait ~100ms each.
        assert time.monotonic() - started >= 0.28

    def test_cohere_default_is_safe_for_trial_keys(self):
        """Trial keys allow 20 calls/minute. Exceeding it is the difference
        between a completed run and a report full of zeros."""
        assert providers._DEFAULT_RPM["cohere"] == 20

    def test_rpm_is_overridable_by_env(self, monkeypatch):
        monkeypatch.setenv("CLARION_EVAL_COHERE_RPM", "500")
        assert providers._rpm_for("cohere") == 500

    def test_malformed_override_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CLARION_EVAL_COHERE_RPM", "lots")
        assert providers._rpm_for("cohere") == 20

    def test_each_model_gets_its_own_gate(self):
        """Cohere rate-limits per model ("past the per-minute request limit for
        this model"), so one gate per model is the correct shape. Sharing a
        single provider-wide gate throttles the whole run to one model's
        ceiling."""
        a = providers.limiter("cohere", "command-a-plus-05-2026")
        b = providers.limiter("cohere", "tiny-aya-earth")
        assert a is not b
        assert a is providers.limiter("cohere", "command-a-plus-05-2026")

    def test_providers_do_not_share_gates(self):
        assert providers.limiter("cohere", "m") is not providers.limiter("anthropic", "m")


class TestJobOrdering:
    def test_jobs_are_interleaved_across_models(self):
        """Model-major ordering points every worker at one model's rate budget
        and stalls there. Consecutive jobs must cycle through models instead."""
        specs = models.resolve(models.DEFAULT_MODELS)
        items = list(range(4))
        jobs = [(s, i) for i in items for s in specs]
        first = [s.key for s, _ in jobs[: len(specs)]]
        assert len(set(first)) == len(specs), (
            "the first N jobs should span all N models, not repeat one"
        )


class TestPreflight:
    """A full run is >1,600 requests and, on a rate-limited key, about an hour.
    A dead model ID must surface in the first ten seconds, not the last — and
    especially not at the judging step, after every generation already
    succeeded."""

    def _fake_chat(self, dead: set[str]):
        def chat(kind, api_name, system, user, **kwargs):
            if api_name in dead:
                return providers.Completion("", 0, error=f"HTTP 404: {api_name}")
            return providers.Completion("OK", 5)

        return chat

    def test_all_reachable_returns_no_failures(self, monkeypatch):
        monkeypatch.setattr(run.providers, "chat", self._fake_chat(set()))
        failures = run._preflight(
            models.resolve(["haiku", "command-a-plus"]), list(judge.DEFAULT_JUDGES), None
        )
        assert failures == []

    def test_dead_generation_model_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            run.providers, "chat", self._fake_chat({"claude-haiku-4-5-20251001"})
        )
        failures = run._preflight(models.resolve(["haiku"]), [], None)
        assert len(failures) == 1
        assert "claude-haiku-4-5-20251001" in failures[0]

    def test_dead_judge_is_reported(self, monkeypatch):
        """The expensive case: generation would have run for an hour first."""
        monkeypatch.setattr(
            run.providers, "chat", self._fake_chat({"claude-sonnet-4-6"})
        )
        failures = run._preflight(
            models.resolve(["haiku"]), list(judge.DEFAULT_JUDGES), None
        )
        assert len(failures) == 1
        assert "judge" in failures[0]

    def test_local_gguf_is_not_probed_over_the_network(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            run.providers,
            "chat",
            lambda *a, **k: called.append(a) or providers.Completion("OK", 1),
        )
        run._preflight(models.resolve(["tiny-aya-earth-local"]), [], None)
        assert not called


class TestRetryPolicy:
    def test_rate_limit_and_server_errors_are_retried(self):
        assert providers._should_retry(429)
        assert providers._should_retry(500)
        assert providers._should_retry(503)

    def test_client_errors_are_not_retried(self):
        """A 400 or 401 will not fix itself; retrying just burns quota."""
        assert not providers._should_retry(400)
        assert not providers._should_retry(401)
        assert not providers._should_retry(404)


class TestQuotaExhaustion:
    """A 429 means two different things and only one is worth waiting for.

    Learned the expensive way: a run hit Cohere's 1,000-calls/month trial cap
    partway through, and every remaining request was retried six times with
    backoff before being recorded as failed — turning instant, permanent
    failures into ~45-second ones across hundreds of calls.
    """

    PER_MINUTE = (
        '{"message":"You are using a Trial key, which is limited to 20 API '
        'calls / minute. You can continue to use the API."}'
    )
    PER_MONTH = (
        '{"message":"You are using a Trial key, which is limited to 1000 API '
        'calls / month. You can continue to use the API."}'
    )

    def test_per_minute_limit_is_retried(self):
        assert not providers.is_quota_exhausted(self.PER_MINUTE)
        assert providers._should_retry(429, self.PER_MINUTE)

    def test_monthly_quota_is_not_retried(self):
        assert providers.is_quota_exhausted(self.PER_MONTH)
        assert not providers._should_retry(429, self.PER_MONTH)

    @pytest.mark.parametrize(
        "body",
        [
            '{"error":{"message":"You exceeded your current quota"}}',
            '{"error":{"type":"insufficient_quota"}}',
            '{"message":"monthly limit reached"}',
            '{"message":"limited to 500 API calls / day"}',
        ],
    )
    def test_other_quota_phrasings_are_recognised(self, body):
        assert providers.is_quota_exhausted(body)

    def test_empty_body_defaults_to_retrying(self):
        """Unknown 429s stay retryable — a spurious retry costs seconds, a
        wrongly-skipped one costs the datapoint."""
        assert not providers.is_quota_exhausted("")
        assert providers._should_retry(429, "")
