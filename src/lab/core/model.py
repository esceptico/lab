"""The records lab keeps on disk, defined once.

campaign.toml       CampaignConfig   written by people and agents
state.json          CampaignState    baseline and lock history, written by lab
runs/<id>/run.json  Run              one per run
experiments/<e>/.labexp.json  ExperimentOrigin
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def now() -> datetime:
    return datetime.now(UTC)


class Verdict(StrEnum):
    KEEP = "keep"
    REVERT = "revert"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


VERDICT_LABELS = {
    Verdict.KEEP: "Kept",
    Verdict.REVERT: "Reverted",
    Verdict.INCONCLUSIVE: "Inconclusive",
    Verdict.FAILED: "Failed",
}
UNJUDGED_LABEL = "Not judged"


class Status(StrEnum):
    RUNNING = "running"
    OK = "ok"  # the command exited 0
    FAILED = "failed"  # it exited non-zero, or could not start
    KILLED = "killed"  # stopped by Ctrl-C, SIGTERM or SIGHUP


class Lock(BaseModel):
    """The eval lock as seen by one run: which epoch it ran in, and whether locked/ matched it."""

    hash: str
    epoch: int
    ok: bool


class Artifact(BaseModel):
    path: str  # relative to the run directory
    title: str = ""


class Figure(Artifact):
    type: str  # a lab.fig chart type


class Run(BaseModel):
    id: str
    campaign: str
    experiment: str
    parent: str | None = None
    hypothesis: str = ""
    prediction: str = ""
    tags: list[str] = []
    command: list[str]
    backend: str = "local"
    host: str = ""
    pid: int | None = None  # the lab process that supervises the run, to tell a lost run from a running one
    lock: Lock
    lib_hash: str | None = None
    snapshot_skipped: list[str] = []
    status: Status = Status.RUNNING
    started_at: datetime
    ended_at: datetime | None = None
    duration_s: float | None = None
    exit_code: int | None = None
    metrics: dict[str, Any] = {}
    cost_usd: float = 0.0
    verdict: Verdict | None = None
    verdict_note: str = ""
    verdict_at: datetime | None = None
    artifacts: list[Artifact] = []
    figures: list[Figure] = []

    def value(self, metric: str) -> float | None:
        v = self.metrics.get(metric)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def finished(self) -> bool:
        return self.status is not Status.RUNNING


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="allow")  # other keys in campaign.toml are the author's notes

    question: str = ""
    metric: str = ""
    goal: Literal["min", "max"] = "min"
    budget_usd: float | None = None
    target: float | None = None  # the value that answers the question, e.g. a published number to reproduce
    noise_floor: float = 0.0
    fmt: int = 3

    def better(self, a: float, b: float) -> bool:
        return a < b if self.goal == "min" else a > b


class LockEpoch(BaseModel):
    hash: str
    at: datetime
    note: str = ""


class CampaignState(BaseModel):
    """What lab keeps per campaign. The baseline is not stored: it follows from the runs (see compare)."""

    locks: list[LockEpoch] = Field(default_factory=list)


class ExperimentOrigin(BaseModel):
    parent: str | None = None
    source: str | None = Field(default=None, alias="from")

    model_config = ConfigDict(populate_by_name=True)
