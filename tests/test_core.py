import signal
import subprocess
import sys
import time
from datetime import timedelta

import pytest

from conftest import run
from lab.cli import main
from lab.core import compare
from lab.core.campaigns import create_campaign
from lab.core.model import CampaignConfig, Lock, Run, Status, Verdict, now
from lab.core.snapshot import hash_tree
from lab.core.store import LabError

# ---------- runs ----------


def test_a_run_records_what_it_did(campaign):
    assert run("train.py", "0.1") == 0
    record = campaign.run("r001")
    assert record.status is Status.OK and record.exit_code == 0
    assert record.metrics == {"loss": pytest.approx(1 / 3 + 0.1), "val_loss": pytest.approx(0.6)}
    assert record.cost_usd == 0.25
    assert [a.path for a in record.artifacts] == ["artifacts/plot.txt"]
    assert [(f.path, f.type) for f in record.figures] == [("figures/loss.json", "line")]
    run_dir = campaign.run_dir("r001")
    assert (run_dir / "code" / "train.py").exists() and (run_dir / "lib" / "shared.py").exists()
    assert "trained 0.1" in (run_dir / "stdout.log").read_text()


def test_the_command_runs_in_its_own_copy(campaign):
    """Outputs land in the run, not the experiment, so parallel runs and later snapshots stay clean."""
    run("train.py")
    assert (campaign.run_dir("r001") / "work" / "plot.txt").exists()
    assert not (campaign.experiments / "base" / "plot.txt").exists()


def test_parent_defaults_and_the_baseline_follows_keep(campaign):
    run("train.py", "0.1")
    run("train.py", "0.05")
    assert campaign.run("r002").parent == "r001"
    main(["verdict", "r001", "keep"])
    assert compare.baseline(campaign.runs()).id == "r001"
    main(["verdict", "r002", "keep"])
    assert compare.baseline(campaign.runs()).id == "r002"
    main(["verdict", "r002", "revert"])
    assert compare.baseline(campaign.runs()).id == "r001"


def test_budget_is_checked_before_each_run(campaign):
    run("train.py")
    run("train.py")
    assert run("train.py") == 0  # starts at 0.50 of 0.60
    assert run("train.py") == 1  # starts at 0.75: refused
    assert len(campaign.runs()) == 3


def test_parallel_runs_get_distinct_ids(campaign):
    procs = [
        subprocess.Popen([sys.executable, "-m", "lab.cli", "run", "--", sys.executable, "-c", "pass"]) for _ in range(4)
    ]
    assert [p.wait() for p in procs] == [0] * 4
    assert [r.id for r in campaign.runs()] == ["r001", "r002", "r003", "r004"]


def test_a_changed_eval_is_recorded_not_refused(campaign):
    run("train.py")
    (campaign.locked / "eval.py").write_text("EVAL = 2\n")
    assert run("train.py") == 0
    assert campaign.run("r002").lock.ok is False
    main(["lock", "--accept", "fixed eval bug"])
    run("train.py")
    assert campaign.run("r003").lock == Lock(hash=hash_tree(campaign.locked), epoch=2, ok=True)


def test_failed_and_unstartable_commands(campaign):
    assert main(["run", "--", sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert campaign.run("r001").status is Status.FAILED
    assert main(["run", "--", "no-such-program --flag"]) == 127
    assert "could not start" in (campaign.run_dir("r002") / "stdout.log").read_text()


def test_sigterm_ends_the_run_as_killed(campaign):
    lab_run = subprocess.Popen(
        [sys.executable, "-m", "lab.cli", "run", "--", sys.executable, "-c", "import time; time.sleep(30)"]
    )
    deadline = time.monotonic() + 10
    while not (campaign.runs_dir / "r001" / "stdout.log").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    lab_run.send_signal(signal.SIGTERM)
    assert lab_run.wait(timeout=10) == 128 + signal.SIGTERM
    assert campaign.run("r001").status is Status.KILLED


def test_a_torn_metrics_line_and_nan_do_not_break_the_record(campaign):
    script = (
        "import os, math; from lab import summary\n"
        "summary(val_loss=float('nan'), acc=0.5)\n"
        "open(os.environ['LAB_RUN_DIR'] + '/metrics.jsonl', 'a').write('{\"kind\": \"summ')\n"
    )
    assert main(["run", "--", sys.executable, "-c", script]) == 0
    record = campaign.run("r001")
    assert record.status is Status.OK and record.metrics == {"val_loss": None, "acc": 0.5}


def test_lib_is_part_of_the_record(campaign, lab):
    main(["run", "--", sys.executable, "-c", "import shared"])
    (lab.lib / "shared.py").write_text("VALUE = 8\n")
    main(["run", "--", sys.executable, "-c", "import shared"])
    first, second = campaign.run("r001"), campaign.run("r002")
    assert (campaign.run_dir("r001") / "lib" / "shared.py").read_text() == "VALUE = 7\n"
    assert first.lib_hash != second.lib_hash


def test_branch_from_a_run(campaign):
    run("train.py")
    main(["new", "exp", "wider", "--from", "r001"])
    assert campaign.origin(campaign.experiments / "wider").parent == "r001"
    main(["run", "-e", "wider", "--", sys.executable, "train.py", "0.2"])
    assert campaign.run("r002").parent == "r001"


# ---------- store ----------


def test_runs_are_ordered_numerically(campaign):
    for n in (999, 1000):
        (campaign.runs_dir / f"r{n}").mkdir(parents=True)
        campaign.save_run(
            Run(
                id=f"r{n}",
                campaign="demo",
                experiment="base",
                command=["x"],
                lock=Lock(hash="h", epoch=1, ok=True),
                started_at=now(),
            )
        )
    assert [r.id for r in campaign.runs()] == ["r999", "r1000"]
    assert campaign.new_run_dir().name == "r1001"


@pytest.mark.parametrize("name", ["../escape", ".hidden", "a/b", ""])
def test_names_cannot_leave_the_lab(lab, name):
    with pytest.raises(LabError):
        create_campaign(lab, name)


def test_questions_with_any_characters_round_trip(lab):
    question = 'He said "it\'s" at C:\\data'
    assert create_campaign(lab, "q", question=question).config().question == question


def test_a_broken_config_names_the_file(campaign):
    (campaign.root / "campaign.toml").write_text("metric = [")
    with pytest.raises(LabError, match=r"campaign\.toml"):
        campaign.config()


# ---------- compare ----------


def record(id: str, value: float | None, *, epoch=1, ok=True, verdict=None, parent=None, at=0) -> Run:
    return Run(
        id=id, campaign="c", experiment="e", command=["x"], parent=parent, metrics={"m": value},
        lock=Lock(hash="h", epoch=epoch, ok=ok), started_at=now(), verdict=verdict,
        verdict_at=now() + timedelta(seconds=at) if verdict else None,
    )  # fmt: skip


def test_delta_only_between_comparable_runs():
    parent = record("r001", 1.0)
    assert compare.delta(record("r002", 0.8, parent="r001"), parent, "m") == pytest.approx(-0.2)
    assert compare.delta(record("r002", 0.8, epoch=2), parent, "m") is None
    assert compare.delta(record("r002", 0.8, ok=False), parent, "m") is None


def test_classify_respects_goal_and_noise():
    config = CampaignConfig(metric="m", goal="min", noise_floor=0.05)
    assert compare.classify(-0.1, config) is compare.Change.BETTER
    assert compare.classify(0.1, config) is compare.Change.WORSE
    assert compare.classify(-0.01, config) is compare.Change.WITHIN_NOISE


def test_baseline_is_the_latest_keep_on_the_current_eval():
    runs = [
        record("r001", 1.0, verdict=Verdict.KEEP, at=1),
        record("r002", 0.9, verdict=Verdict.KEEP, at=2, ok=False),  # changed eval, not accepted
        record("r003", 0.95, epoch=2, verdict=Verdict.REVERT),
    ]
    assert compare.baseline(runs) is None  # epoch 2 has no keep yet
    assert compare.baseline(runs[:2]).id == "r001"


def test_best_so_far_resets_with_the_epoch():
    runs = [record("r001", 1.0, verdict=Verdict.KEEP), record("r002", 0.9), record("r003", 2.0, epoch=2)]
    assert compare.best_so_far(runs, "m") == {"r001": 1.0, "r002": 1.0, "r003": None}


def test_branch_from_an_experiment_or_a_short_run_id(campaign):
    run("train.py")
    assert main(["new", "exp", "copy", "--from", "base"]) == 0  # an experiment name
    assert main(["new", "exp", "again", "--from", "1"]) == 0  # 1 is r001
    assert (campaign.experiments / "copy" / "train.py").exists() and (
        campaign.experiments / "again" / "train.py"
    ).exists()


def test_a_nan_cost_is_refused_and_never_poisons_spend(campaign):
    (campaign.experiments / "base" / "nan.py").write_text("from lab import cost\ncost(float('nan'))\ncost(0.1)\n")
    run("nan.py")
    assert campaign.run("r001").cost_usd == pytest.approx(0.1)
    assert main(["cost", "r001", "nan", "-m", "x"]) == 1
    run("train.py")  # spend still adds up, so the next run starts


def test_data_linked_into_locked_is_hashed(campaign, tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    (data / "dev.jsonl").write_text("a\n")
    (campaign.locked / "data").symlink_to(data, target_is_directory=True)
    before = hash_tree(campaign.locked)
    (data / "dev.jsonl").write_text("b\n")
    assert hash_tree(campaign.locked) != before


def test_accepting_a_new_eval_leaves_no_baseline_until_a_keep_on_it(campaign):
    run("train.py")
    main(["verdict", "r001", "keep"])
    assert campaign.baseline().id == "r001"
    (campaign.locked / "eval.py").write_text("EVAL = 2\n")
    main(["lock", "--accept", "new split"])
    assert campaign.baseline() is None


def test_a_run_without_a_result_cannot_be_kept(campaign):
    (campaign.experiments / "base" / "silent.py").write_text("print('no summary')\n")
    run("silent.py")
    assert main(["verdict", "r001", "keep"]) == 1
    assert campaign.run("r001").verdict is None
