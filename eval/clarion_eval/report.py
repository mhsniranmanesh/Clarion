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

    add(f"# Evaluation run `{manifest['timestamp_utc']}`")
    add("")
    add(
        f"{n} utterances "
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

    if manifest["dataset_reviewed"] < n:
        add(
            f"> **Not publishable.** Only {manifest['dataset_reviewed']} of {n} "
            "utterances are marked `reviewed: true`. The rest are unverified drafts."
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
        "verbatim, case-sensitive, token-boundary aware. *Fully English* — no Persian/Arabic "
        "script left in the output. *Format clean* — no preamble or trailing commentary, "
        "which the shared prompt forbids. Averages are over all "
        f"{n} utterances; a failed generation counts as zero."
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
