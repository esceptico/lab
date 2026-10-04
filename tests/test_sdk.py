"""The code that runs inside experiment environments: lab (logging), lab.fig, lab.events."""

import json
import subprocess
import sys

import pytest

from lab import artifact, events, fig, log, summary
from lab.stats import brier, reliability_bins


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_RUN_DIR", str(tmp_path))
    return tmp_path


def test_helpers_do_nothing_outside_a_run(tmp_path, monkeypatch):
    monkeypatch.delenv("LAB_RUN_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    log(step=1, loss=1.0)
    summary(val_loss=1.0)
    assert fig.bars(["a"], {"x": [1]}, title="t")["type"] == "bars"
    assert list(tmp_path.iterdir()) == []


def test_reserved_names_are_refused(run_dir):
    with pytest.raises(ValueError, match="reserved"):
        log(step=0, t=0.7)


def test_values_become_json(run_dir):
    log(step=0, loss=float("nan"), hist=[1, 2])
    assert events.read(run_dir / events.FILE).points[0]["loss"] is None
    assert json.loads((run_dir / events.FILE).read_text())["hist"] == [1, 2]


def test_artifacts_with_the_same_name_are_both_kept(run_dir, tmp_path_factory):
    a, b = tmp_path_factory.mktemp("a") / "p.txt", tmp_path_factory.mktemp("b") / "p.txt"
    a.write_text("a")
    b.write_text("b")
    artifact(a)
    artifact(b)
    assert [x["path"] for x in events.read(run_dir / events.FILE).artifacts] == ["artifacts/p.txt", "artifacts/p-2.txt"]


def test_figures_are_written_as_specs(run_dir):
    fig.line({"a": [1, 2, 3], "b": [3, 2, float("nan")]}, title="Two lines")
    fig.line({"a": [1]}, title="Two lines")
    spec = json.loads((run_dir / "figures" / "two-lines.json").read_text())
    assert spec["series"][1]["y"] == [3, 2, None] and spec["source"] == [run_dir.name]
    assert (run_dir / "figures" / "two-lines-2.json").exists()
    assert [f["type"] for f in events.read(run_dir / events.FILE).figures] == ["line", "line"]


def test_calibration_numbers():
    bins, ece = reliability_bins([0.1, 0.8, 0.95, 0.4], [0, 1, 1, 1])
    assert ece == pytest.approx(0.2375) and [b["n"] for b in bins] == [1, 1, 1, 1]
    assert brier([[1.0, 0.0], [1.0, 0.0]], [0, 1]) == pytest.approx(1.0)


def test_in_run_modules_need_no_cli_dependencies():
    """They are imported inside experiment environments, which have no pydantic."""
    code = (
        "import sys; sys.modules['pydantic'] = None; sys.modules['markdown_it'] = None; sys.modules['tomlkit'] = None\n"
        "import lab, lab.fig, lab.events, lab.stats, lab.remote, lab.bench_run, lab.ssh_app"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
