"""The on-disk layout of a lab, and the only code that reads or writes its records.

<lab>/lab.toml                   marks the root (or LAB_HOME)
<lab>/lib/                       shared research code, on every run's PYTHONPATH
<lab>/templates/<name>/          experiment starting points
<lab>/campaigns/<name>/
    campaign.toml                CampaignConfig
    state.json                   CampaignState
    .lock                        taken around every read-modify-write of campaign files
    locked/                      data prep and eval, hashed per run
    experiments/<exp>/           free code (+ .labexp.json: ExperimentOrigin)
    runs/<id>/                   run.json, metrics.jsonl, stdout.log, code/, lib/, work/, artifacts/, figures/
    findings.md
"""

import contextlib
import fcntl
import os
import re
import secrets
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from . import compare
from .model import CampaignConfig, CampaignState, ExperimentOrigin, Run

MARKER = "lab.toml"
OLD_MARKER = "labs.toml"  # before the rename; `lab sync` renames it
ORIGIN_FILE = ".labexp.json"
NAME = re.compile(r"^[A-Za-z0-9][\w.-]*$")
RUN_ID = re.compile(r"^r(\d+)$")


class LabError(Exception):
    """A problem the user can fix; the CLI prints it without a traceback."""


def valid_name(name: str, what: str) -> str:
    """Names become directory names, so they may not contain separators or start with a dot."""
    if not NAME.match(name):
        raise LabError(
            f"invalid {what} name {name!r}: use letters, digits, '.', '_' or '-', starting with a letter or digit"
        )
    return name


def write_model(path: Path, record: BaseModel) -> None:
    """Atomic and durable: readers and parallel writers never see half a record."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "x") as f:
        f.write(record.model_dump_json(indent=2, by_alias=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_model[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        return model.model_validate_json(path.read_text())
    except ValueError as error:
        raise LabError(f"cannot read {path}: {error}") from error


@dataclass(frozen=True)
class Lab:
    root: Path

    @classmethod
    def find(cls, start: Path | None = None) -> "Lab":
        env = os.environ.get("LAB_HOME")
        if env:
            return cls(Path(env).expanduser().resolve())
        here = (start or Path.cwd()).resolve()
        for directory in (here, *here.parents):
            if (directory / MARKER).exists() or (directory / OLD_MARKER).exists():
                return cls(directory)
        raise LabError(f"not inside a lab (no {MARKER} above here): `lab init <dir>` creates one, or set LAB_HOME")

    @property
    def lib(self) -> Path:
        return self.root / "lib"

    @property
    def templates(self) -> Path:
        return self.root / "templates"

    @property
    def campaigns_dir(self) -> Path:
        return self.root / "campaigns"

    def campaigns(self) -> list["Campaign"]:
        return sorted((Campaign(p.parent) for p in self.campaigns_dir.glob("*/campaign.toml")), key=lambda c: c.name)

    def campaign(self, name: str) -> "Campaign":
        root = self.campaigns_dir / valid_name(name, "campaign")
        if not (root / "campaign.toml").exists():
            raise LabError(f"no campaign {name}")
        return Campaign(root)

    def locate(self, start: Path | None = None) -> tuple["Campaign", Path | None]:
        """The campaign around `start`, and the experiment directory if `start` is inside one."""
        here = (start or Path.cwd()).resolve()
        for directory in (here, *here.parents):
            if (directory / "campaign.toml").exists():
                campaign = Campaign(directory)
                try:
                    parts = here.relative_to(campaign.experiments).parts
                except ValueError:
                    return campaign, None
                return campaign, (campaign.experiments / parts[0]) if parts else None
        raise LabError("not inside a campaign (no campaign.toml above here); pass -c <campaign>")


@dataclass(frozen=True)
class Campaign:
    root: Path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def locked(self) -> Path:
        return self.root / "locked"

    @property
    def experiments(self) -> Path:
        return self.root / "experiments"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def findings(self) -> Path:
        return self.root / "findings.md"

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Exclusive across processes: parallel `lab run` / `lab verdict` calls take turns on campaign files."""
        with open(self.root / ".lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)  # released when the file closes
            yield

    def config(self) -> CampaignConfig:
        path = self.root / "campaign.toml"
        try:
            return CampaignConfig.model_validate(tomllib.loads(path.read_text()))
        except ValueError as error:
            raise LabError(f"cannot read {path}: {error}") from error

    def state(self) -> CampaignState:
        path = self.root / "state.json"
        return read_model(path, CampaignState) if path.exists() else CampaignState()

    @property
    def epoch(self) -> int:
        """The accepted eval: the number of lock epochs, which a run may not have reached yet."""
        return len(self.state().locks)

    def baseline(self) -> Run | None:
        return compare.baseline(self.runs(), self.epoch)

    def save_state(self, state: CampaignState) -> None:
        write_model(self.root / "state.json", state)

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise LabError(f"invalid run id {run_id!r} (expected r001, r002, …)")
        return self.runs_dir / run_id

    def runs(self) -> list[Run]:
        """Every run, in the order they were started (r999 before r1000)."""
        records = []
        for path in self.runs_dir.glob("r*/run.json"):
            try:
                records.append(read_model(path, Run))
            except LabError as error:  # one damaged record must not stop every command on the campaign
                print(f"lab: warning: skipping {error}", file=sys.stderr)
        return sorted(records, key=lambda r: int(RUN_ID.match(r.id)[1]))

    def run(self, run_id: str) -> Run:
        path = self.run_dir(run_id) / "run.json"
        if not path.exists():
            raise LabError(f"no run {run_id} in {self.name}; `lab ls` lists them")
        return read_model(path, Run)

    def save_run(self, run: Run) -> None:
        write_model(self.run_dir(run.id) / "run.json", run)

    def new_run_dir(self) -> Path:
        """Claim the next run id. mkdir is atomic, so parallel runs never share one."""
        self.runs_dir.mkdir(exist_ok=True)
        taken = [int(m[1]) for p in self.runs_dir.iterdir() if (m := RUN_ID.match(p.name))]
        n = max(taken, default=0) + 1
        while True:
            path = self.runs_dir / f"r{n:03d}"
            try:
                path.mkdir()
                return path
            except FileExistsError:
                n += 1

    def experiment(self, name: str) -> Path:
        path = self.experiments / valid_name(name, "experiment")
        if not path.is_dir():
            raise LabError(f"no experiment {name} in {self.name}")
        return path

    def origin(self, experiment: Path) -> ExperimentOrigin:
        path = experiment / ORIGIN_FILE
        return read_model(path, ExperimentOrigin) if path.exists() else ExperimentOrigin()

    def save_origin(self, experiment: Path, origin: ExperimentOrigin) -> None:
        write_model(experiment / ORIGIN_FILE, origin)
