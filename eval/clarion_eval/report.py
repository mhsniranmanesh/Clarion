"""Renders a run directory into a Markdown report.

Design rule: nothing here may hide a failure. Every table reports how many of
the N utterances a model actually completed, and averages are taken over the
whole dataset with failed generations scored as zero. A model that crashes on
half the set cannot look good by averaging over the half that worked.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _metric_value(record: dict, key: str) -> float:
    """One record's contribution to a metric average.

    A failed generation scores zero rather than being skipped, so a model cannot
    improve its average by crashing on the hard utterances.
    """
    if record.get("error"):
        return 0.0
    value = record.get(key)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value or 0.0)


def render(run_dir: Path) -> str:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    generations = _read_jsonl(run_dir / "generations.jsonl")
    judgements = _read_jsonl(run_dir / "judgements.jsonl")

    labels = {m["key"]: m["label"] for m in manifest["models"]}
    order = [m["key"] for m in manifest["models"]]
    n = manifest["dataset_size"]

    by_model: dict[str, list[dict]] = {k: [] for k in order}
    for record in generations:
        by_model.setdefault(record["model"], []).append(record)

    lines: list[str] = []
    add = lines.append

    lang_stats = manifest.get("languages", [])

    add(f"# Evaluation run `{manifest['timestamp_utc']}`")
    add("")
    add(
        f"{n} utterances across {len(lang_stats)} languages "
        f"({manifest['dataset_reviewed']} native-speaker reviewed) x "
        f"{len(order)} models. "
        f"temperature={manifest['temperature']}, max_tokens={manifest['max_tokens']}."
    )
    add("")
    add(
        f"System prompt SHA-256 `{manifest['system_prompt_sha256'][:16]}…` — identical "
        "to the prompt compiled into the shipping app."
    )
    add("")

    # ── Publishability, per language ─────────────────────────────────────────
    if lang_stats:
        unpublishable = [s for s in lang_stats if not s["publishable"]]
        if unpublishable:
            names = ", ".join(s["name"] for s in unpublishable)
            add(
                f"> **Not publishable for {names}.** Review status is tracked per "
                "language; only languages at 100% native-speaker review below carry "
                "publishable numbers. The rest are unverified drafts."
            )
            add("")

        add("## Dataset")
        add("")
        add("| Language | Utterances | Native-reviewed | Authored by | Residue check | Publishable |")
        add("|---|---|---|---|---|---|")
        for s in lang_stats:
            authored = (
                "native speaker"
                if s["native_authored"] == s["total"]
                else f"{s['native_authored']}/{s['total']} native, rest LLM-drafted"
            )
            check = "exact (script)" if s["detection"] == "script" else "heuristic (function words)"
            add(
                f"| {s['name']} (`{s['code']}`) | {s['total']} "
                f"| {s['reviewed']}/{s['total']} | {authored} | {check} "
                f"| {'yes' if s['publishable'] else '**no**'} |"
            )
        add("")

    # ── Deterministic ────────────────────────────────────────────────────────
    add("## Deterministic metrics")
    add("")
    add(
        "Computed from the run files with no model in the loop. These carry the "
        "headline claims."
    )
    add("")
    add(
        "| Model | Completed | Identifier recall | Fully English | Format clean | Median latency |"
    )
    add("|---|---|---|---|---|---|")

    for key in order:
        records = by_model.get(key, [])
        if not records:
            add(f"| {labels.get(key, key)} | 0/{n} | — | — | — | — |")
            continue

        ok = [r for r in records if not r.get("error")]
        # Failures score zero rather than being excluded.
        recalls = [
            r["identifier_recall"] if not r.get("error") else 0.0 for r in records
        ]
        english = [
            1.0 if (not r.get("error") and r["fully_english"]) else 0.0
            for r in records
        ]
        fmt = [
            1.0 if (not r.get("error") and r["format_clean"]) else 0.0 for r in records
        ]
        latencies = [r["latency_ms"] for r in ok] or [0]

        add(
            f"| {labels.get(key, key)} "
            f"| {len(ok)}/{len(records)} "
            f"| {_pct(_mean(recalls))} "
            f"| {_pct(_mean(english))} "
            f"| {_pct(_mean(fmt))} "
            f"| {int(statistics.median(latencies))} ms |"
        )
    add("")
    add(
        "*Identifier recall* — share of technical tokens the speaker said that survived "
        "verbatim, case-sensitive, token-boundary aware. *Fully English* — no source-language "
        "text left in the output; measured exactly by Unicode script for Persian, Arabic, "
        "Chinese and Russian, and heuristically by function-word detection for Spanish and "
        "French, which share the Latin alphabet with English. *Format clean* — no preamble "
        "or trailing commentary, which the shared prompt forbids. Averages are over all "
        f"{n} utterances; a failed generation counts as zero."
    )
    add("")

    # ── Per language ─────────────────────────────────────────────────────────
    langs_present = [s["code"] for s in lang_stats]
    if len(langs_present) > 1:
        add("### By language")
        add("")
        add(
            "The same three deterministic metrics, split by source language. This is "
            "where a model that is strong on one language and weak on another stops "
            "being hidden by the average above."
        )
        add("")

        for metric_key, metric_name in (
            ("identifier_recall", "Identifier recall"),
            ("fully_english", "Fully English"),
            ("format_clean", "Format clean"),
        ):
            add(f"**{metric_name}**")
            add("")
            names = {s["code"]: s["name"] for s in lang_stats}
            add("| Model | " + " | ".join(names[c] for c in langs_present) + " |")
            add("|---" * (1 + len(langs_present)) + "|")
            for key in order:
                cells = []
                for code in langs_present:
                    rows = [
                        r
                        for r in by_model.get(key, [])
                        if r.get("lang") == code
                    ]
                    if not rows:
                        cells.append("—")
                        continue
                    values = [_metric_value(r, metric_key) for r in rows]
                    cells.append(_pct(_mean(values)))
                add(f"| {labels.get(key, key)} | " + " | ".join(cells) + " |")
            add("")

    # ── Regional tuning ──────────────────────────────────────────────────────
    variants = [k for k in order if k.startswith("tiny-aya-")]
    if len(variants) > 1 and len(langs_present) > 1:
        add("### Regional tuning")
        add("")
        add(
            "The Tiny Aya variants are the same 3.35B model over the same 70 languages, "
            "differing only in which region's languages they were tuned toward. Holding "
            "the dataset, prompt and decoding fixed, any difference between these rows "
            "is attributable to the regional tuning alone. Cohere's model cards claim "
            "Earth covers Persian and Arabic, and Water covers Chinese, Russian, Spanish "
            "and French."
        )
        add("")
        add("| Language | Claimed variant | " + " | ".join(labels.get(v, v) for v in variants) + " | Claim holds |")
        add("|---" * (3 + len(variants)) + "|")

        claimed_by_lang = {
            "fa": "tiny-aya-earth",
            "ar": "tiny-aya-earth",
            "zh": "tiny-aya-water",
            "ru": "tiny-aya-water",
            "es": "tiny-aya-water",
            "fr": "tiny-aya-water",
        }
        names = {s["code"]: s["name"] for s in lang_stats}
        suppressed = False

        for code in langs_present:
            scores: dict[str, float | None] = {}
            complete: dict[str, bool] = {}
            cells = []
            for v in variants:
                rows = [r for r in by_model.get(v, []) if r.get("lang") == code]
                ok = [r for r in rows if not r.get("error")]
                if not rows:
                    scores[v] = None
                    complete[v] = False
                    cells.append("—")
                    continue
                scores[v] = _mean([_metric_value(r, "identifier_recall") for r in rows])
                complete[v] = len(ok) == len(rows)
                cells.append(
                    _pct(scores[v])
                    if complete[v]
                    else f"{_pct(scores[v])} ({len(ok)}/{len(rows)})"
                )

            claimed = claimed_by_lang.get(code)
            scored = {k: s for k, s in scores.items() if s is not None}

            # A variant that was rate-limited or errored scores zero by the
            # no-dropping rule, which is right for the headline table and wrong
            # here: "Water scored 0%" would read as a finding when the truth is
            # that Water was never successfully asked. No verdict unless every
            # variant answered every utterance for this language.
            if not scored or claimed not in scored:
                verdict = "—"
            elif not all(complete[v] for v in scored):
                verdict = "*insufficient data*"
                suppressed = True
            else:
                best = max(scored, key=lambda k: scored[k])
                if abs(scored[best] - scored[claimed]) < 1e-9:
                    verdict = "tied"
                elif best == claimed:
                    verdict = "yes"
                else:
                    verdict = f"**no** — {labels.get(best, best)} leads"

            add(
                f"| {names[code]} | {labels.get(claimed, claimed or '—')} | "
                + " | ".join(cells)
                + f" | {verdict} |"
            )
        add("")
        add(
            "Compared on identifier recall, the metric that is exact for every language "
            "in the set. A claim marked **no** means the region-matched variant did not "
            "lead on the language it is documented to cover."
        )
        if suppressed:
            add("")
            add(
                "> Rows marked *insufficient data* had at least one variant fail to "
                "complete every utterance — the completed count is shown in the cell. "
                "Failed generations score zero everywhere else in this report, which is "
                "correct for measuring a model but would fabricate a regional-tuning "
                "result here: a variant that was rate-limited never got to answer. No "
                "verdict is drawn until every variant has answered every utterance."
            )
        add("")

    # ── Judged ───────────────────────────────────────────────────────────────
    if judgements:
        add("## Judged metrics (blind)")
        add("")
        judge_keys = sorted({j["judge"] for j in judgements})
        add(
            f"Candidates were shuffled and relabelled per utterance; judges never saw "
            f"model names. Judges: {', '.join(f'`{k}`' for k in judge_keys)}."
        )
        add("")

        per_judge: dict[str, dict[str, list[tuple[int, int]]]] = {}
        for verdict in judgements:
            bucket = per_judge.setdefault(verdict["judge"], {})
            for model_key, score in verdict.get("scores", {}).items():
                bucket.setdefault(model_key, []).append(
                    (score["fidelity"], score["quality"])
                )

        header = "| Model |" + "".join(
            f" {jk} fidelity | {jk} quality |" for jk in judge_keys
        )
        add(header)
        add("|---" * (1 + 2 * len(judge_keys)) + "|")

        for key in order:
            row = [labels.get(key, key)]
            for jk in judge_keys:
                pairs = per_judge.get(jk, {}).get(key, [])
                if pairs:
                    row.append(f"{_mean([p[0] for p in pairs]):.2f}")
                    row.append(f"{_mean([p[1] for p in pairs]):.2f}")
                else:
                    row += ["—", "—"]
            add("| " + " | ".join(row) + " |")
        add("")

        scored_counts = {
            jk: sum(len(v) for v in per_judge.get(jk, {}).values())
            for jk in judge_keys
        }
        add(
            "Judged pairs per judge: "
            + ", ".join(f"`{k}`={v}" for k, v in scored_counts.items())
            + f" (expected {n * len(order)} each)."
        )
        add("")

        if len(judge_keys) >= 2:
            a, b = judge_keys[0], judge_keys[1]
            deltas = []
            for key in order:
                pa = per_judge.get(a, {}).get(key, [])
                pb = per_judge.get(b, {}).get(key, [])
                if pa and pb:
                    deltas.append(
                        abs(_mean([p[1] for p in pa]) - _mean([p[1] for p in pb]))
                    )
            if deltas:
                add(
                    f"**Judge agreement** — mean absolute difference between `{a}` and "
                    f"`{b}` on per-model quality averages: {_mean(deltas):.2f} points "
                    "on a 1–5 scale. Large values mean the judged numbers should be "
                    "treated as weak evidence."
                )
                add("")

    # ── Failures ─────────────────────────────────────────────────────────────
    failures = [r for r in generations if r.get("error")]
    if failures:
        add("## Failures")
        add("")
        add(f"{len(failures)} of {len(generations)} generations failed.")
        add("")
        add("| Model | Utterance | Error |")
        add("|---|---|---|")
        for record in failures[:40]:
            err = str(record["error"]).replace("|", "\\|")[:160]
            add(f"| {record['model']} | {record['utterance_id']} | {err} |")
        if len(failures) > 40:
            add(f"| … | | {len(failures) - 40} more |")
        add("")

    add("---")
    add("")
    add(
        "Raw generations, judgements and the run manifest are committed next to this "
        "report. Every number above is recomputable from them."
    )
    add("")
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Re-render a run directory.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    report = render(args.run_dir)
    (args.run_dir / "REPORT.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
