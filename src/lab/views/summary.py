"""How a run is presented on any page, computed once from the records and the comparison rules."""

import shlex
from datetime import UTC, datetime

from ..core import compare
from ..core import runs as lifecycle
from ..core.model import UNJUDGED_LABEL, VERDICT_LABELS, CampaignConfig, Run, Status

# Every word the pages print for a run's state; the page scripts read them from here.
LABELS = {str(v): label for v, label in VERDICT_LABELS.items()} | {"none": UNJUDGED_LABEL, "running": "Running"}


def summarize(run: Run, runs: dict[str, Run], config: CampaignConfig) -> dict:
    parent = runs.get(run.parent or "")
    change = compare.delta(run, parent, config.metric)
    killed = run.status is Status.KILLED
    lost = lifecycle.lost(run)
    return {
        "id": run.id,
        "exp": run.experiment,
        "parent": run.parent,
        "value": run.value(config.metric),
        "delta": change,
        "change": str(compare.classify(change, config)) if change is not None else None,
        "comparable": run.lock.ok,
        "verdict": str(run.verdict) if run.verdict else None,
        "note": run.verdict_note
        or ("Stopped by hand." if killed else "Lost: its lab process ended without a result." if lost else ""),
        "status": str(Status.FAILED if killed or lost else run.status),
        "lost": lost,
        "cost": run.cost_usd,
        "dur": (datetime.now(UTC) - run.started_at).total_seconds()
        if run.status is Status.RUNNING and not lost
        else run.duration_s,
        "backend": run.backend,
        "hyp": run.hypothesis,
        "pred": run.prediction,
        "epoch": run.lock.epoch,
        "tags": run.tags,
        "command": shlex.join(run.command),
        "started": run.started_at.astimezone().strftime("%d %b %H:%M"),
    }
