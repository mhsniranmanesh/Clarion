"""CLI: run models over the dataset, score, and write a run directory.

    python -m clarion_eval.run --models haiku command-a-plus tiny-aya-earth

Every utterance x model pair is attempted exactly once and recorded, including
failures. Nothing is dropped, so averages are always over the full dataset and
the completion count is reported alongside every score.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from . import dataset, judge as judge_mod, metrics, models, providers

RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"


def _load_env() -> None:
    """Loads eval/.env then repo-root .env, without clobbering real env vars."""
    here = Path(__file__).resolve().parents[1]
    load_dotenv(here / ".env")
    load_dotenv(here.parent / ".env")


def _generate(
    specs: list[models.ModelSpec],
    items: list[dataset.Utterance],
    gguf_path: str | None,
    workers: int,
) -> list[dict]:
    jobs = [(spec, item) for spec in specs for item in items]
    total = len(jobs)
    done = 0

    def one(job):
        spec, item = job
        completion = providers.complete(spec, item.text, gguf_path=gguf_path)
        return {
            "utterance_id": item.id,
            "model": spec.key,
            "output": completion.text,
            "latency_ms": completion.latency_ms,
            "error": completion.error,
        }

    # Local GGUF is a single in-process model; parallel calls would contend on
    # it and distort the latency numbers we are trying to measure.
    if any(s.kind == "local_gguf" for s in specs):
        workers = 1

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for record in pool.map(one, jobs):
            done += 1
            status = "ok " if record["error"] is None else "ERR"
            print(
                f"  [{done:>4}/{total}] {status} {record['model']:<22} {record['utterance_id']}",
                file=sys.stderr,
            )
            if record["error"]:
                print(f"        {record['error'][:160]}", file=sys.stderr)
            results.append(record)
    return results


def _score(generations: list[dict], items: list[dataset.Utterance]) -> list[dict]:
    by_id = {i.id: i for i in items}
    scored = []
    for record in generations:
        item = by_id[record["utterance_id"]]
        det = metrics.score_all(record["output"], item.identifiers, item.gloss)
        scored.append({**record, **det.to_dict()})
    return scored


def _judge(
    judges: list[judge_mod.JudgeSpec],
    generations: list[dict],
    items: list[dataset.Utterance],
    workers: int,
) -> list[dict]:
    by_id = {i.id: i for i in items}
    grouped: dict[str, dict[str, str]] = {}
    for record in generations:
        # An errored generation still gets judged, as an empty candidate. Hiding
        # failures from the judge would flatter models that failed.
        grouped.setdefault(record["utterance_id"], {})[record["model"]] = record["output"]

    jobs = [(j, uid, outs) for j in judges for uid, outs in sorted(grouped.items())]
    total = len(jobs)
    done = 0

    def one(job):
        judge_spec, uid, outs = job
        item = by_id[uid]
        verdict = judge_mod.judge_utterance(
            judge_spec, uid, item.text, item.gloss, outs
        )
        return {"judge": judge_spec.key, "utterance_id": uid, **verdict}

    verdicts: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for verdict in pool.map(one, jobs):
            done += 1
            status = "ok " if not verdict.get("error") else "ERR"
            print(
                f"  [{done:>4}/{total}] {status} {verdict['judge']:<22} {verdict['utterance_id']}",
                file=sys.stderr,
            )
            if verdict.get("error"):
                print(f"        {str(verdict['error'])[:160]}", file=sys.stderr)
            verdicts.append(verdict)
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="clarion-eval",
        description="Evaluate prompt structuring on code-switched Persian/English speech.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=models.DEFAULT_MODELS,
        help=f"Model keys. Available: {', '.join(models.REGISTRY)}",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--gguf-path", default=None, help="Path to a GGUF file for local models"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM judging and report deterministic metrics only",
    )
    parser.add_argument(
        "--judge",
        nargs="+",
        default=None,
        help="Judge specs as kind:model, e.g. anthropic:claude-sonnet-4-6-20250514",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Only run the first N utterances"
    )
    parser.add_argument("--tag", default=None, help="Label for the run directory")
    args = parser.parse_args()

    _load_env()

    specs = models.resolve(args.models)
    items = dataset.load(args.dataset)
    if args.limit:
        items = items[: args.limit]

    unreviewed = [i.id for i in items if not i.reviewed]
    if unreviewed:
        print(
            f"WARNING: {len(unreviewed)}/{len(items)} utterances are not marked "
            f"reviewed=true. Results computed from unreviewed drafts are not "
            f"publishable.\n",
            file=sys.stderr,
        )

    judges: list[judge_mod.JudgeSpec] = []
    if not args.no_judge:
        if args.judge:
            for raw in args.judge:
                if ":" not in raw:
                    parser.error(f"--judge expects kind:model, got {raw!r}")
                kind, api_name = raw.split(":", 1)
                judges.append(
                    judge_mod.JudgeSpec(f"judge-{kind}", kind, api_name, api_name)
                )
        else:
            judges = list(judge_mod.DEFAULT_JUDGES)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / (f"{stamp}-{args.tag}" if args.tag else stamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Dataset: {dataset.summarise(items)}", file=sys.stderr)
    print(f"Models:  {', '.join(s.key for s in specs)}", file=sys.stderr)
    print(f"Run dir: {run_dir}\n", file=sys.stderr)

    print("Generating...", file=sys.stderr)
    generations = _generate(specs, items, args.gguf_path, args.workers)

    print("\nScoring (deterministic)...", file=sys.stderr)
    scored = _score(generations, items)

    verdicts: list[dict] = []
    if judges:
        print("\nJudging (blind)...", file=sys.stderr)
        verdicts = _judge(judges, generations, items, args.workers)

    (run_dir / "generations.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in scored) + "\n",
        encoding="utf-8",
    )
    if verdicts:
        (run_dir / "judgements.jsonl").write_text(
            "\n".join(json.dumps(v, ensure_ascii=False) for v in verdicts) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "timestamp_utc": stamp,
        "models": [
            {"key": s.key, "api_name": s.api_name, "kind": s.kind, "label": s.label}
            for s in specs
        ],
        "judges": [{"key": j.key, "kind": j.kind, "api_name": j.api_name} for j in judges],
        "dataset": str(args.dataset or dataset.DEFAULT_DATASET),
        "dataset_size": len(items),
        "dataset_reviewed": sum(1 for i in items if i.reviewed),
        "temperature": providers.TEMPERATURE,
        "max_tokens": providers.MAX_TOKENS,
        "system_prompt_sha256": _sha256(providers.system_prompt()),
        "gguf_path": args.gguf_path,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    from .report import render

    report = render(run_dir)
    (run_dir / "REPORT.md").write_text(report, encoding="utf-8")

    print(f"\nWrote {run_dir}/", file=sys.stderr)
    print(report)
    return 0


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
