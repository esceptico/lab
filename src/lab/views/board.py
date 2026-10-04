"""`lab board`: one self-contained page over every campaign's runs."""

import json
import os
from pathlib import Path

from markdown_it import MarkdownIt

from .. import events
from ..core import compare, findings
from ..core.model import CampaignConfig, CampaignState, Run
from ..core.store import Campaign, Lab
from . import diff, page, text
from .summary import LABELS, summarize
from .term import layout

# The curve shown in the run pane: the first of these that was logged, else the campaign metric, else the first key.
PREFERRED_CURVES = ("loss", "train_loss", "val_loss")
TAIL = 40  # log lines the run page shows
FILES = ("stdout.log", "metrics.jsonl", "run.json")  # the record files a run page lists, beside its artifacts
# Findings are Markdown: **bold**, `code`, links; raw HTML stays text.
INLINE = MarkdownIt("commonmark", {"html": False})


def render(lab: Lab, out: Path) -> str:
    data = {"labels": LABELS, "campaigns": [campaign_data(c, out) for c in lab.campaigns()]}
    return page.render("board.html", data)


def campaign_data(campaign: Campaign, out: Path) -> dict:
    config, state = campaign.config(), campaign.state()
    runs = campaign.runs()
    by_id = {r.id: r for r in runs}
    baseline = compare.baseline(runs, campaign.epoch)
    value = baseline.value(config.metric) if baseline else None  # a kept run with no result is not a best result
    best = compare.best_so_far(runs, config.metric)
    last = max((r.started_at for r in runs), default=None)
    return {
        "name": campaign.name,
        "question": config.question or campaign.name,
        "metric": config.metric,
        "goal": config.goal,
        "noise": config.noise_floor,
        "budget": config.budget_usd,
        "fmt": config.fmt,
        "epoch": compare.current_epoch(runs),
        "epochs": epochs(runs, state),
        "best": baseline.id if value is not None else None,
        "toGo": compare.to_target(value, config) if value is not None else None,
        "spent": compare.spent(runs),
        "gain": compare.gain(runs, baseline, config),
        "target": config.target,
        "updated": last.astimezone().strftime("%d %b %H:%M") if last else None,
        "ls": terminal_ls(campaign),
        "findings": [[INLINE.renderInline(f.text), list(f.refs)] for f in findings.read(campaign.findings)],
        "next": [[INLINE.renderInline(f.text), list(f.refs)] for f in findings.read(campaign.findings, findings.NEXT)],
        "runs": [run_data(campaign, config, run, by_id, out) | {"bestSoFar": best[run.id]} for run in runs],
    }


def run_data(campaign: Campaign, config: CampaignConfig, run: Run, by_id: dict[str, Run], out: Path) -> dict:
    run_dir = campaign.run_dir(run.id)
    changes = diff.between(campaign, by_id.get(run.parent or ""), run)
    return summarize(run, by_id, config) | {
        "curve": curve(run_dir, config.metric),
        "figures": [json.loads((run_dir / f.path).read_text()) for f in run.figures if (run_dir / f.path).exists()],
        "artifacts": [
            {"path": a.path, "title": a.title, "href": os.path.relpath(run_dir / a.path, out)} for a in run.artifacts
        ],
        "changes": {"command": changes.command, "diff": changes.diff},
        "metrics": {k: v for k in run.metrics if (v := run.value(k)) is not None},  # every logged number, for compare
        "record": record(campaign, run, run_dir),
    }


def record(campaign: Campaign, run: Run, run_dir: Path) -> dict:
    """What the run page shows as evidence: where the run lives, the files lab keeps, the log's end, the raw record."""
    log = run_dir / "stdout.log"
    text = log.read_text(errors="replace").rstrip("\n") if log.exists() else ""
    lines = [line.split("\r")[-1] for line in text.split("\n")] if text else []  # a progress bar keeps its last frame
    return {
        "host": run.host,
        "exit": run.exit_code,
        "lock": run.lock.hash,
        "lib": run.lib_hash,
        "dir": str(run_dir.relative_to(campaign.root.parent.parent)),
        "files": [{"name": n, "size": (run_dir / n).stat().st_size} for n in FILES if (run_dir / n).is_file()],
        "artSizes": {a.path: (run_dir / a.path).stat().st_size for a in run.artifacts if (run_dir / a.path).is_file()},
        "tail": "\n".join(lines[-TAIL:]),
        "show": run.model_dump_json(indent=2),
    }


def curve(run_dir: Path, metric: str) -> dict | None:
    logged = events.read(run_dir / events.FILE)
    keys = logged.curve_keys()
    if not keys:
        return None
    key = next((k for k in (*PREFERRED_CURVES, metric) if k in keys), keys[0])
    x, y = logged.curve(key)
    return {"key": key, "x": x, "y": y}


def epochs(runs: list[Run], state: CampaignState) -> list[dict]:
    """Where each eval lock epoch after the first begins, with the note given when it was accepted."""
    starts: dict[int, Run] = {}
    for run in runs:
        starts.setdefault(run.lock.epoch, run)
    return [
        {
            "at": run.id,
            "epoch": epoch,
            "note": f"Eval changed: {state.locks[epoch - 1].note if epoch <= len(state.locks) else ''}. "
            "Runs before this are not comparable with runs after.",
        }
        for epoch, run in sorted(starts.items())
        if epoch > 1
    ]


def terminal_ls(campaign: Campaign) -> str:
    """`lab ls` as a terminal 150 columns wide shows it, without colour: the board's Terminal view."""
    with layout(terminal=True, colour=False, width=150):
        return text.ls(campaign)
