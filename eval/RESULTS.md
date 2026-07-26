# Results

> **No results yet.**
>
> The harness is built and tested, but no scored run has been published. Two things
> must happen first, in order:
>
> 1. The 35 draft utterances in `data/utterances.jsonl` need a native-speaker rewrite
>    and must be flipped to `reviewed: true`. Until then the runner prints a warning and
>    every report carries a **Not publishable** banner.
> 2. A `COHERE_API_KEY` must be present so the Cohere models can actually run.
>
> This file will be replaced by the generated report of the first publishable run —
> whatever it says. If Cohere's models lose to the Haiku baseline, that result gets
> published here with examples, because a negative result a reader can verify is worth
> more than a favourable one they cannot.

## How to produce this file

```bash
cd eval
source .venv/bin/activate
python -m clarion_eval.run --models haiku command-a-plus command-a-translate tiny-aya-earth
cp runs/<timestamp>/REPORT.md RESULTS.md
git add -f eval/runs/<timestamp>
```

Methodology, metric definitions and the limitations that must be cited alongside any
number here are documented in [README.md](README.md).
