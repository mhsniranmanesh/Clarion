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

from . import dataset, judge as judge_mod, languages, metrics, models, providers

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
    # Item-major, so consecutive jobs cycle through models rather than running
    # one model to completion before starting the next. Providers rate-limit per
    # model, so a model-major order points every worker at a single model's
    # budget and stalls on it; interleaving lets N models absorb N x that rate.
    jobs = [(spec, item) for item in items for spec in specs]
    total = len(jobs)
    done = 0

    def one(job):
        spec, item = job
        completion = providers.complete(spec, item.text, gguf_path=gguf_path)
        return {
            "utterance_id": item.id,
            "lang": item.lang,
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


def _preflight(
    specs: list[models.ModelSpec],
    judges: list[judge_mod.JudgeSpec],
    gguf_path: str | None,
) -> list[str]:
    """Checks every model and judge answers before committing to a full run.

    A full six-language run is over a thousand requests and, on a rate-limited
    key, the better part of an hour. Discovering a dead model ID at the end of
    that — or worse, at the *judging* step after every generation succeeded — is
    an hour lost to a typo. Eight one-token requests up front is cheap insurance.

    Returns a list of human-readable failures; empty means everything answered.
    """
    probes: list[tuple[str, str, str]] = [
        (s.key, s.kind, s.api_name) for s in specs if s.kind != "local_gguf"
    ]
    probes += [(f"judge:{j.key}", j.kind, j.api_name) for j in judges]

    failures = []
    for label, kind, api_name in probes:
        result = providers.chat(
            kind, api_name, "Reply with the single word OK.", "Go.",
            temperature=0.0, max_tokens=16, gguf_path=gguf_path,
        )
        status = "ok" if result.ok else "FAIL"
        print(f"  {status:<4} {label:<24} {api_name}", file=sys.stderr)
        if not result.ok:
            failures.append(f"{label} ({api_name}): {str(result.error)[:200]}")
    return failures


def _score(generations: list[dict], items: list[dataset.Utterance]) -> list[dict]:
    by_id = {i.id: i for i in items}
    scored = []
    for record in generations:
        item = by_id[record["utterance_id"]]
        det = metrics.score_all(
            record["output"], item.identifiers, item.gloss, item.lang
        )
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
            judge_spec, uid, item.text, item.gloss, outs, item.lang
        )
        return {
            "judge": judge_spec.key,
            "utterance_id": uid,
            "lang": item.lang,
            **verdict,
        }

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


def _rejudge(args, parser) -> int:
    """Re-runs judging over a completed run's generations, in place.

    Generation is the expensive half — a six-language run is 1,260 requests and
    real money. Judging is a tenth of that and is where the fixable mistakes
    live: a bad judge model ID, a token budget too small for the number of
    candidates, a rubric that needed sharpening. Without this, fixing any of
    those means paying for every generation a second time to get at the cheap
    part, which is enough friction that the tempting alternative is to publish
    the broken judgements.
    """
    run_dir = args.rejudge
    generations_path = run_dir / "generations.jsonl"
    manifest_path = run_dir / "manifest.json"
    if not generations_path.exists() or not manifest_path.exists():
        parser.error(f"{run_dir} is not a completed run directory")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generations = [
        json.loads(line)
        for line in generations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    items = dataset.load(_absolute(manifest.get("dataset")))
    keep = {r["utterance_id"] for r in generations}
    items = [i for i in items if i.id in keep]

    judges: list[judge_mod.JudgeSpec] = []
    if args.judge:
        for raw in args.judge:
            if ":" not in raw:
                parser.error(f"--judge expects kind:model, got {raw!r}")
            kind, api_name = raw.split(":", 1)
            judges.append(judge_mod.JudgeSpec(f"judge-{kind}", kind, api_name, api_name))
    else:
        judges = list(judge_mod.DEFAULT_JUDGES)

    print(f"Re-judging {run_dir}", file=sys.stderr)
    print(f"  {len(generations)} generations over {len(items)} utterances", file=sys.stderr)
    print(f"  judges: {', '.join(j.api_name for j in judges)}\n", file=sys.stderr)

    if not args.no_preflight:
        failures = _preflight([], judges, None)
        if failures:
            print("\nPreflight failed:", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            return 1
        print("", file=sys.stderr)

    verdicts = _judge(judges, generations, items, args.workers)

    (run_dir / "judgements.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in verdicts) + "\n",
        encoding="utf-8",
    )
    manifest["judges"] = [
        {"key": j.key, "kind": j.kind, "api_name": j.api_name} for j in judges
    ]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    from .report import render

    report = render(run_dir)
    (run_dir / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"\nRewrote {run_dir}/judgements.jsonl and REPORT.md", file=sys.stderr)
    print(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="clarion-eval",
        description="Evaluate prompt structuring on code-switched developer speech "
        "across Persian, Arabic, Chinese, Russian, Spanish and French.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=models.DEFAULT_MODELS,
        help=f"Model keys. Available: {', '.join(models.REGISTRY)}",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--langs",
        nargs="+",
        default=None,
        help=f"Restrict to these languages. Available: {', '.join(languages.codes())}",
    )
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
        "--limit",
        type=int,
        default=None,
        help="Only run the first N utterances per language",
    )
    parser.add_argument("--tag", default=None, help="Label for the run directory")
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="Skip the model reachability check before generating",
    )
    parser.add_argument(
        "--rejudge",
        type=Path,
        default=None,
        metavar="RUN_DIR",
        help="Re-judge an existing run's generations in place, without "
        "regenerating them. Use after fixing a judging problem.",
    )
    args = parser.parse_args()

    _load_env()

    if args.rejudge:
        return _rejudge(args, parser)

    specs = models.resolve(args.models)
    try:
        items = dataset.load(args.dataset, args.langs)
    except KeyError as exc:
        parser.error(str(exc))
    if args.limit:
        # Per language, so --limit on a six-language set still covers all six
        # rather than returning 5 Arabic rows and nothing else.
        capped: list[dataset.Utterance] = []
        counts: dict[str, int] = {}
        for item in items:
            if counts.get(item.lang, 0) < args.limit:
                counts[item.lang] = counts.get(item.lang, 0) + 1
                capped.append(item)
        items = capped

    stats = dataset.language_stats(items)
    unpublishable = [s for s in stats if not s.publishable]
    if unpublishable:
        detail = ", ".join(f"{s.code} {s.reviewed}/{s.total}" for s in unpublishable)
        print(
            f"WARNING: not every language is fully native-speaker reviewed "
            f"({detail}). Per-language results for those languages are computed "
            f"from unverified drafts and are not publishable.\n",
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

    print(f"Dataset: {dataset.summarise(items)}", file=sys.stderr)
    print(f"Models:  {', '.join(s.key for s in specs)}", file=sys.stderr)

    # Before the run directory exists, so a failed preflight leaves nothing behind.
    if not args.no_preflight:
        print("\nPreflight...", file=sys.stderr)
        failures = _preflight(specs, judges, args.gguf_path)
        if failures:
            print("\nPreflight failed:", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            print(
                "\nAborting before generating. Fix the model IDs, or pass "
                "--no-preflight to run anyway.",
                file=sys.stderr,
            )
            return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / (f"{stamp}-{args.tag}" if args.tag else stamp)
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nRun dir: {run_dir}\n", file=sys.stderr)

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
        "dataset": _portable(args.dataset or dataset.DEFAULT_DATASET),
        "dataset_size": len(items),
        "dataset_reviewed": sum(1 for i in items if i.reviewed),
        "languages": [
            {
                "code": s.code,
                "name": s.name,
                "total": s.total,
                "reviewed": s.reviewed,
                "native_authored": s.native_authored,
                "detection": s.detection,
                "publishable": s.publishable,
            }
            for s in stats
        ],
        "temperature": providers.TEMPERATURE,
        "max_tokens": providers.MAX_TOKENS,
        "system_prompt_sha256": _sha256(providers.system_prompt()),
        "gguf_path": _portable(args.gguf_path),
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


# Run directories get committed, so the manifest is a public artifact. An
# absolute path bakes the author's home directory into it and, worse, points at
# a location nobody else has — `--rejudge` on a fresh checkout would fail to
# find the dataset it is supposed to re-score against.
def _portable(path: Path | str | None) -> str | None:
    """Repo-relative if the path is inside the repo, absolute otherwise."""
    if path is None:
        return None
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(providers.REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _absolute(path: str | None) -> Path | None:
    """Inverse of `_portable`. Older manifests stored absolute paths; those
    still resolve, so runs recorded before this change stay re-judgeable."""
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else providers.REPO_ROOT / candidate


if __name__ == "__main__":
    raise SystemExit(main())
