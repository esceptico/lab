"""The run lifecycle: start (budget, lock, snapshot, execute, record) and judge."""

import math
import os
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import events
from . import compare, process
from .model import Artifact, Figure, Lock, LockEpoch, Run, Status, Verdict, now
from .snapshot import copy_code, copy_tree, hash_tree
from .store import Campaign, Lab, LabError

PACKAGE = Path(__file__).resolve().parents[1]  # the `lab` package


def lab_path() -> Path:
    """A folder holding only a link to the `lab` package, for a run's PYTHONPATH. The package's own parent
    is site-packages in an installed lab, and putting that first would give user code lab's dependencies."""
    home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "lab" / "path"
    home.mkdir(parents=True, exist_ok=True)
    link = home / "lab"
    if not link.exists() or link.resolve() != PACKAGE:
        temp = home / f".lab-{os.getpid()}"  # replaced in one step, so a parallel run never sees no link
        temp.unlink(missing_ok=True)
        temp.symlink_to(PACKAGE, target_is_directory=True)
        os.replace(temp, link)
    return home


@dataclass(frozen=True)
class RunRequest:
    experiment: Path
    command: list[str]
    hypothesis: str = ""
    prediction: str = ""
    parent: str | None = None
    tags: tuple[str, ...] = ()
    quiet: bool = False


def to_stderr(message: str) -> None:
    print(f"lab: warning: {message}", file=sys.stderr)


def spent(campaign: Campaign) -> float:
    """Recorded cost of finished runs plus what running runs have logged so far."""
    runs = campaign.runs()
    in_flight = sum(events.read(campaign.run_dir(r.id) / events.FILE).cost for r in runs if r.status is Status.RUNNING)
    return compare.spent(runs) + in_flight


def check_budget(campaign: Campaign) -> None:
    cap = campaign.config().budget_usd
    if cap is not None and (used := spent(campaign)) >= cap:
        raise LabError(f"budget spent: ${used:.2f} of ${cap:.2f}. Raise budget_usd in campaign.toml to continue.")


def current_lock(campaign: Campaign) -> Lock:
    """Hash locked/. The first run sets epoch 1; a later change is recorded as not ok, never refused."""
    digest = hash_tree(campaign.locked)
    state = campaign.state()
    if not state.locks:
        state.locks.append(LockEpoch(hash=digest, at=now(), note="first run"))
        campaign.save_state(state)
    return Lock(hash=digest, epoch=len(state.locks), ok=digest == state.locks[-1].hash)


def accept_lock(campaign: Campaign, note: str) -> int:
    with campaign.lock():
        state = campaign.state()
        state.locks.append(LockEpoch(hash=hash_tree(campaign.locked), at=now(), note=note))
        campaign.save_state(state)
        return len(state.locks)


def default_parent(campaign: Campaign, experiment: Path) -> str | None:
    """The last run of this experiment that has a result (a crash has nothing to compare with), else where
    the experiment branched from, else the baseline."""
    runs, metric = campaign.runs(), campaign.config().metric
    previous = [r for r in runs if r.experiment == experiment.name and r.value(metric) is not None]
    if previous:
        return previous[-1].id
    if parent := campaign.origin(experiment).parent:
        return parent
    best = compare.baseline(runs, campaign.epoch)
    return best.id if best else None


def run_environment(lab: Lab, campaign: Campaign, run_dir: Path) -> dict[str, str]:
    paths = [str(lab_path()), str(lab.lib)]  # `from lab import log` and lib/ work from any interpreter
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(paths),
        "PYTHONUNBUFFERED": "1",
        "LAB_HOME": str(lab.root),
        "LAB_RUN_DIR": str(run_dir),
        "LAB_RUN_ID": run_dir.name,
        "LAB_CAMPAIGN_DIR": str(campaign.root),
        "LAB_LOCKED_DIR": str(campaign.locked),
    }


def start(lab: Lab, campaign: Campaign, request: RunRequest, notify: Callable[[str], None] = to_stderr) -> Run:
    """Record and execute one run; the record always ends in a terminal status.

    The command runs in runs/<id>/work, a copy of the snapshot, so the record is exactly what ran,
    edits to the experiment during the run cannot leak in, and parallel runs never share a folder.
    """
    if not request.command:
        raise LabError("nothing to run: lab run [options] -- <command>")
    parent = request.parent if request.parent is not None else default_parent(campaign, request.experiment)
    with campaign.lock():  # budget check and id claim are one step, so parallel starts cannot overshoot
        check_budget(campaign)
        lock = current_lock(campaign)
        run_dir = campaign.new_run_dir()
        run = Run(
            id=run_dir.name,
            campaign=campaign.name,
            experiment=request.experiment.name,
            parent=parent,
            hypothesis=request.hypothesis,
            prediction=request.prediction,
            tags=list(request.tags),
            command=request.command,
            host=socket.gethostname(),
            pid=os.getpid(),
            lock=lock,
            started_at=now(),
        )
        campaign.save_run(run)

    outcome = process.Outcome(Status.FAILED, 1, 0.0)  # what the record says if anything below raises
    try:
        skipped = copy_tree(request.experiment, run_dir / "code")
        copy_code(request.experiment, run_dir / "work")
        if lab.lib.is_dir():  # lib/ is on the path, so it is part of what ran
            skipped += [f"lib/{p}" for p in copy_tree(lab.lib, run_dir / "lib")]
        run = run.model_copy(update={"lib_hash": hash_tree(lab.lib), "snapshot_skipped": skipped})
        campaign.save_run(run)
        if skipped:
            notify(f"too large to record in the snapshot: {', '.join(skipped[:3])}")
        if not lock.ok:
            notify(
                f"locked/ changed since lock epoch {lock.epoch}: {run.id} is not comparable with earlier runs. "
                'If the change is intended, `lab lock --accept "why"`.'
            )
        if not request.hypothesis:
            notify("no hypothesis (-H). The run is recorded, but a verdict will be hard to read later.")
        env = run_environment(lab, campaign, run_dir)
        outcome = process.run(request.command, run_dir / "work", env, run_dir / "stdout.log", request.quiet)
    except KeyboardInterrupt:
        outcome = process.Outcome(Status.KILLED, 130, 0.0)
        raise
    finally:
        run = finish(campaign, run, outcome)
    return run


def closed(campaign: Campaign, run: Run, status: Status, exit_code: int | None, seconds: float) -> Run:
    """The record of an ended run: its outcome plus everything it logged."""
    logged = events.read(campaign.run_dir(run.id) / events.FILE)
    return run.model_copy(
        update={
            "status": status,
            "exit_code": exit_code,
            "ended_at": now(),
            "duration_s": round(seconds, 1),
            "metrics": logged.summary,
            "cost_usd": round(logged.cost, 4),
            "artifacts": [Artifact(**a) for a in logged.artifacts],
            "figures": [Figure(**f) for f in logged.figures],
        }
    )


def finish(campaign: Campaign, run: Run, outcome: process.Outcome) -> Run:
    finished = closed(campaign, run, outcome.status, outcome.exit_code, outcome.seconds)
    with campaign.lock():  # a verdict given while the run was going must survive this write
        current = campaign.run(run.id)
        finished = finished.model_copy(
            update={k: getattr(current, k) for k in ("verdict", "verdict_note", "verdict_at")}
        )
        campaign.save_run(finished)
    return finished


def record_cost(campaign: Campaign, run_id: str, usd: float, note: str, total: bool = False) -> Run:
    """Log an amount a service billed for a run, typically after it ended (bills post late).

    With total, the run's cost becomes exactly `usd`: the difference is logged as a correction, so
    what was recorded before stays readable in metrics.jsonl.
    """
    if not math.isfinite(usd):
        raise LabError(f"{usd} is not an amount of dollars")
    with campaign.lock():
        run = campaign.run(run_id)
        run_dir = campaign.run_dir(run_id)
        logged = events.read(run_dir / events.FILE).cost
        amount = usd - logged if total else usd
        events.append(run_dir, events.COST, usd=amount, note=f"correction to ${usd:.2f}: {note}" if total else note)
        if run.finished:  # a running run picks the amount up when it ends
            run = run.model_copy(update={"cost_usd": round(logged + amount, 4)})
            campaign.save_run(run)
        return run


def lost(run: Run) -> bool:
    """Recorded as running, but its lab process on this machine is gone (killed hard, or the machine rebooted)."""
    if run.status is not Status.RUNNING or run.pid is None or run.host != socket.gethostname():
        return False  # a run from another machine is taken on trust
    try:
        os.kill(run.pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:  # alive, owned by someone else
        return False
    return False


def judge(campaign: Campaign, run_id: str, verdict: Verdict, note: str, force: bool = False) -> Run | None:
    """Record a verdict; return the baseline that results from it.

    Judging a lost run closes it as killed; so does force, for a run lab cannot check (another machine, or
    recorded before runs kept their pid). If its process was in fact alive, its own finish overwrites the status.
    """
    with campaign.lock():
        run = campaign.run(run_id)
        if run.status is Status.RUNNING and not (lost(run) or force):
            raise LabError(
                f"{run_id} is still running; judge it when it ends (`lab ls`), or pass --force if it is dead"
            )
        if run.status is Status.RUNNING:
            run = closed(campaign, run, Status.KILLED, None, (now() - run.started_at).total_seconds())
        metric = campaign.config().metric
        if verdict is Verdict.KEEP and run.value(metric) is None:
            raise LabError(
                f"{run_id} reported no {metric}, so it cannot be the baseline: judge it failed or inconclusive"
            )
        judged = run.model_copy(update={"verdict": verdict, "verdict_note": note, "verdict_at": now()})
        campaign.save_run(judged)
        return campaign.baseline()
