from pathlib import Path
from runpy import run_path

from lab import bench_run
from lab.ops import doctor

ROOT = Path(__file__).resolve().parent.parent


def mc(lls, target):
    """A multiple-choice sample as lm-eval writes it to samples_*.jsonl: target as text, arguments keyed."""
    return {
        "target": str(target),
        "arguments": {f"gen_args_{i}": {"arg_0": "q", "arg_1": f" {c}"} for i, c in enumerate("ABCD"[: len(lls)])},
        "filtered_resps": [[str(v), "False"] for v in lls],
    }


def test_multiple_choice_probabilities():
    probs, gold = bench_run.choice_probabilities(mc([-1.0, -3.0], 0))
    assert gold == 0 and probs[0] > probs[1] and abs(sum(probs) - 1) < 1e-9
    assert bench_run.choice_probabilities(mc([-3.0, -1.0], "B"))[1] == 1  # gold given as the answer text
    assert bench_run.choice_probabilities(mc([-1.0, -2.0], "Z")) is None  # gold not among the choices
    assert bench_run.choice_probabilities({"target": "x", "filtered_resps": ["free text"]}) is None


def test_sample_files_match_their_task_exactly():
    assert bench_run.sample_task(Path("samples_mmlu_pro_2026-09-23T09-10-25.942515.jsonl")) == "mmlu_pro"
    assert bench_run.sample_task(Path("samples_mmlu_2026-09-23T09-10-25.942515.jsonl")) == "mmlu"


def test_doctor_reports_every_service():
    names = [c.name for c in doctor.checks()]
    assert {"tinker", "prime", "modal", "runpod", "hugging face"} <= set(names)


def test_skill_references_are_current():
    generated = run_path(str(ROOT / "scripts" / "skill_reference.py"))
    references = ROOT / "src" / "lab" / "skill" / "references"
    cli = (references / "cli.md").read_text()
    assert cli == generated["cli_md"](), "run scripts/skill_reference.py"
    assert (references / "figures.md").read_text() == generated["figures_md"]()
    assert (references / "running.md").read_text() == generated["running"]()
    for command in (
        "init",
        "sync",
        "new campaign",
        "new exp",
        "run",
        "verdict",
        "lock",
        "board",
        "bench",
        "doctor",
        "report",
    ):
        assert f"## lab {command}\n" in cli
    running = (references / "running.md").read_text()
    assert "- `interp`:" in running and "### interp.ablate" in running


def test_bench_keeps_each_filter_of_a_metric(monkeypatch):
    recorded = {}
    monkeypatch.setattr(bench_run, "summary", lambda **values: recorded.update(values))
    monkeypatch.setattr(bench_run.fig, "bars", lambda *a, **k: None)
    bench_run.record({"gsm8k": {"exact_match,strict-match": 0.3, "exact_match,flexible-extract": 0.55, "alias": "gsm8k"},
                      "arc_easy": {"acc,none": 0.8, "acc_stderr,none": 0.01}})  # fmt: skip
    assert recorded == {"gsm8k/exact_match/strict-match": 0.3, "gsm8k/exact_match/flexible-extract": 0.55,
                        "arc_easy/acc": 0.8}  # fmt: skip
