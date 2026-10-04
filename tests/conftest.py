import sys

import pytest

from lab.cli import main
from lab.core.campaigns import create_campaign, create_experiment
from lab.core.store import Campaign, Lab

TRAIN = """\
import sys
from lab import artifact, cost, fig, log, summary
lr = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1
for step in range(3):
    log(step=step, loss=1.0 / (step + 1) + lr)
summary(val_loss=0.5 + lr)
cost(0.25, "fake api")
open("plot.txt", "w").write("x")
artifact("plot.txt", "a plot")
fig.line({"loss": [1.0, 0.5, 0.33]}, title="Loss")
print("trained", lr)
"""


@pytest.fixture
def lab(tmp_path, monkeypatch) -> Lab:
    (tmp_path / "lab.toml").write_text("")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "shared.py").write_text("VALUE = 7\n")
    monkeypatch.delenv("LAB_HOME", raising=False)
    monkeypatch.delenv("LAB_RUN_DIR", raising=False)
    return Lab(tmp_path)


@pytest.fixture
def campaign(lab, monkeypatch) -> Campaign:
    campaign = create_campaign(lab, "demo", metric="val_loss", budget_usd=0.6)
    experiment = create_experiment(lab, campaign, "base")
    (experiment / "train.py").write_text(TRAIN)
    (campaign.locked / "eval.py").write_text("EVAL = 1\n")
    monkeypatch.chdir(experiment)
    return campaign


def run(*args: str, hypothesis: str = "h") -> int:
    """`lab run` from the current experiment folder, with this interpreter."""
    return main(["run", "-H", hypothesis, "--", sys.executable, *args])
