import json
import os
import subprocess
import sys
import time

import pytest

from conftest import run
from lab.cli import main
from lab.core.model import Status
from lab.ops import workspace


def test_init_creates_a_lab_and_sync_keeps_edited_guidance(tmp_path, capsys):
    root = tmp_path / "research"
    assert main(["init", str(root)]) == 0
    out = capsys.readouterr()
    assert "created a lab" in out.out and "next: cd" in out.err
    assert (root / "lab.toml").exists() and (root / ".claude/skills/lab/SKILL.md").exists()
    assert (root / ".agents/skills/lab/references/cli.md").exists()
    assert "board/" in (root / ".gitignore").read_text()
    assert main(["init", str(root)]) == 1
    assert "already a lab" in capsys.readouterr().err

    (root / "AGENTS.md").write_text("# mine\n")
    changes = workspace.sync(root)
    assert changes.kept == ["AGENTS.md"] and (root / "AGENTS.md").read_text() == "# mine\n"
    assert workspace.MANAGED in (root / "CLAUDE.md").read_text()


def test_a_lab_from_before_the_rename_is_found_and_sync_renames_its_marker(tmp_path, monkeypatch):
    (tmp_path / "labs.toml").write_text("")
    monkeypatch.chdir(tmp_path)
    assert main(["new", "campaign", "c", "--metric", "loss"]) == 0
    workspace.sync(tmp_path)
    assert (tmp_path / "lab.toml").exists() and not (tmp_path / "labs.toml").exists()


def test_outside_a_lab_the_error_names_lab_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAB_HOME", raising=False)
    assert main(["ls"]) == 1
    assert capsys.readouterr().err.startswith("lab: error: not inside a lab")


def test_run_result_on_stdout_and_next_step_on_stderr(campaign, capsys):
    assert run("train.py") == 0
    out = capsys.readouterr()
    assert out.out.splitlines()[-1].startswith("r001 ok in") and "val_loss 0.6" in out.out
    assert "next: lab verdict r001" in out.err


def test_ls_json_is_machine_readable(campaign, capsys):
    run("train.py")
    main(["verdict", "r001", "keep"])
    capsys.readouterr()
    assert main(["ls", "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["metric"] == "val_loss"
    (row,) = listing["runs"]
    assert row["value"] == pytest.approx(0.6) and row["baseline"] and row["verdict"] == "keep"


def test_templates_json(lab, monkeypatch, capsys):
    monkeypatch.chdir(lab.root)
    main(["templates", "--json"])
    assert {"interp", "modal-custom", "prime-rl", "tinker-sft"} <= {
        t["name"] for t in json.loads(capsys.readouterr().out)
    }


def test_detached_run_outlives_the_caller_and_records_normally(campaign, capsys):
    assert main(["run", "--detach", "-H", "bg", "--", sys.executable, "train.py"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("r001 running in the background")
    deadline = time.monotonic() + 30
    while campaign.run("r001").status is Status.RUNNING and time.monotonic() < deadline:
        time.sleep(0.1)
    run = campaign.run("r001")
    assert run.status is Status.OK and run.hypothesis == "bg" and run.value("val_loss") == pytest.approx(0.6)


def test_a_lost_run_is_shown_and_closed_by_its_verdict(campaign, capsys):
    run("train.py")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    campaign.save_run(campaign.run("r001").model_copy(update={"status": Status.RUNNING, "pid": dead.pid}))
    main(["ls"])
    head, row = capsys.readouterr().out.splitlines()[-2:]  # piped: one fact per column
    assert dict(zip(head.split("\t"), row.split("\t"), strict=True))["status"] == "lost"
    assert main(["verdict", "r001", "failed", "-m", "killed"]) == 0
    assert campaign.run("r001").status is Status.KILLED


def test_verdict_waits_for_a_running_run(campaign, capsys):
    run("train.py")
    campaign.save_run(campaign.run("r001").model_copy(update={"status": Status.RUNNING, "pid": os.getpid()}))
    assert main(["verdict", "r001", "keep"]) == 1
    assert "still running" in capsys.readouterr().err
    assert main(["verdict", "r001", "failed", "--force"]) == 0
    assert campaign.run("r001").status is Status.KILLED


def test_cost_after_the_run_adds_or_replaces_the_logged_amount(campaign, capsys):
    run("train.py")  # logs $0.25
    assert main(["cost", "r001", "1.5", "-m", "billing"]) == 0
    assert campaign.run("r001").cost_usd == pytest.approx(1.75)
    assert main(["cost", "r001", "2.8", "-m", "runpodctl billing pods", "--total"]) == 0
    assert campaign.run("r001").cost_usd == pytest.approx(2.8)
    assert "cost is now $2.80" in capsys.readouterr().out


def test_status_ls_show_compare_read_the_same_runs(campaign, capsys):
    run("train.py")
    main(["verdict", "1", "keep"])  # 1 and r1 are r001
    run("train.py", "0.05")
    capsys.readouterr()
    assert main(["status"]) == 0 and "Best kept" in capsys.readouterr().out
    assert main(["ls"]) == 0
    head, *rows = capsys.readouterr().out.splitlines()
    first = dict(zip(head.split("\t"), rows[0].split("\t"), strict=True))  # piped: one fact per column
    assert first["verdict"] == "Kept" and first["baseline"] == "yes" and first["lock"] == "1"
    assert main(["show", "r2"]) == 0 and "vs r001" in capsys.readouterr().out
    assert main(["compare", "2", "--json"]) == 0
    pair = json.loads(capsys.readouterr().out)
    assert pair["a"]["id"] == "r002" and pair["b"]["id"] == "r001" and pair["changes"]["command"]
    assert main(["--json", "status"]) == 0 and json.loads(capsys.readouterr().out)["best"]["run"] == "r001"


def test_errors_show_usage_an_example_and_near_commands(campaign, capsys):
    with pytest.raises(SystemExit):
        main(["verdict"])
    err = capsys.readouterr().err
    assert err.startswith("lab verdict: missing run, verdict") and "e.g. lab verdict" in err
    with pytest.raises(SystemExit):
        main(["lss"])
    assert "did you mean `lab ls`" in capsys.readouterr().err
