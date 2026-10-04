"""Run lm-evaluation-harness inside a lab run; record every metric, plus ECE and Brier for multiple-choice tasks.

Started by `lab bench`. For multiple-choice tasks, a softmax over the choices' log-likelihoods gives a
probability per choice. The samples format was checked against lm-eval d6de8164: `filtered_resps` holds
[loglikelihood, is_greedy] per choice (written as strings), and `target` is the gold index or answer text.
"""

import argparse
import json
import math
import re
import shlex
import subprocess
import sys
from pathlib import Path

from lab import artifact, fig, run_dir, summary
from lab.stats import brier, reliability_bins


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="hf")
    p.add_argument("--model-args", required=True)
    p.add_argument("--tasks", required=True)
    p.add_argument("--limit", type=float)
    p.add_argument("--num-fewshot", type=int)
    p.add_argument("--extra", default="", help="more lm_eval flags, quoted")
    args = p.parse_args()

    out = (run_dir() or Path.cwd()) / "lm_eval"
    command = [
        sys.executable, "-m", "lm_eval", "--model", args.model, "--model_args", args.model_args, "--tasks", args.tasks,
        "--batch_size", "auto", "--output_path", str(out), "--log_samples",
        *(["--limit", str(args.limit)] if args.limit else []),
        *(["--num_fewshot", str(args.num_fewshot)] if args.num_fewshot is not None else []),
        *shlex.split(args.extra),
    ]  # fmt: skip
    print("$", shlex.join(command), flush=True)
    if code := subprocess.call(command):
        return code

    results_file = next(out.rglob("results_*.json"), None)
    if results_file is None:
        print(f"lm-eval wrote no results under {out}", file=sys.stderr)
        return 1
    results = json.loads(results_file.read_text())["results"]
    record(results)
    artifact(results_file, "lm-eval results")

    calibration = {}
    for task in results:
        samples = [
            json.loads(line)
            for f in out.rglob("samples_*.jsonl")
            if sample_task(f) == task
            for line in f.read_text().splitlines()
            if line
        ]
        scored = [s for s in map(choice_probabilities, samples) if s]
        if not scored:
            continue
        probs, gold = zip(*scored, strict=True)
        confidence = [max(p) for p in probs]
        correct = [p.index(max(p)) == g for p, g in scored]
        _, ece = reliability_bins(confidence, correct)
        summary(**{f"{task}/ece": ece, f"{task}/brier": brier(list(probs), list(gold))})
        calibration[task] = (confidence, correct)
    if calibration:
        fig.reliability(
            calibration,
            title="Calibration on multiple-choice tasks",
            caption="Confidence = softmax over the choices' log-likelihoods.",
        )
    return 0


def sample_task(path: Path) -> str:
    """samples_<task>_<timestamp>.jsonl → <task> (task names may contain underscores)."""
    return re.sub(r"^samples_|_\d{4}-\d{2}-\d{2}T[\d\-.]+\.jsonl$", "", path.name)


def record(results: dict) -> None:
    values, scores = {}, {}
    for task, metrics in results.items():
        for key, value in metrics.items():
            name, _, kept_by = key.partition(",")  # "exact_match,strict-match": a metric under one filter
            if isinstance(value, (int, float)) and "stderr" not in name:
                label = name if kept_by in ("", "none") else f"{name}/{kept_by}"
                values[f"{task}/{label}"] = value
                if name in ("acc", "exact_match") and task not in scores:
                    scores[task] = (label, value)
    summary(**values)
    if scores:
        fig.bars(
            [f"{task} ({label})" if "/" in label else task for task, (label, _) in scores.items()],
            {"score": [100 * v for _, v in scores.values()]},
            domain=(0, 100),
            title="Benchmark scores",
            sub="acc or exact_match, %",
        )


def choice_probabilities(sample: dict) -> tuple[list[float], int] | None:
    """(probability per choice, gold index) for a multiple-choice sample; None for other task types."""
    responses = sample.get("filtered_resps") or []
    try:
        lls = [float(r[0]) for r in responses]
    except (TypeError, ValueError, IndexError):
        return None
    gold = gold_index(sample)
    if len(lls) < 2 or gold is None or gold >= len(lls):
        return None
    top = max(lls)
    exps = [math.exp(v - top) for v in lls]
    return [e / sum(exps) for e in exps], gold


def gold_index(sample: dict) -> int | None:
    """The correct choice. lm-eval writes `target` as text: an index ("2") or the answer's own text ("(B)"),
    which is matched against each choice's continuation in `arguments`."""
    target = str(sample["target"]).strip()
    if target.isdigit():
        return int(target)
    # The samples file stores arguments as {"gen_args_0": {"arg_0": context, "arg_1": continuation}, ...}
    arguments = sample.get("arguments") or {}
    choices = arguments.values() if isinstance(arguments, dict) else arguments
    continuations = [str(c.get("arg_1", "")).strip() if isinstance(c, dict) else None for c in choices]
    matches = [i for i, c in enumerate(continuations) if c == target]
    return matches[0] if len(matches) == 1 else None


if __name__ == "__main__":
    sys.exit(main())
