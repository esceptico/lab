"""Logging from code running under `lab run`.

    from lab import log, summary, cost, artifact, fig

    log(step=100, loss=0.41, jac_rank=37)   # a point on a curve
    summary(val_loss=0.38)                  # the numbers this run is judged by
    cost(1.20, "tinker sft")                # money spent outside this machine
    artifact("spectrum.png", "Jacobian spectrum, layer 12")

Outside `lab run` every call does nothing, so the same script runs standalone.

This module, `lab.fig`, `lab.events`, `lab.remote`, `lab.ssh_app` and `lab.bench_run` run inside
experiment environments on the standard library alone; `lab.modal_app` needs `modal` and `lab.hf_fetch`
`huggingface_hub`, which their callers install. The CLI's internals live in `lab.core`, `lab.views` and `lab.ops`.
"""

import math
import os
import shutil
import sys
from pathlib import Path

from . import events

__all__ = ["artifact", "cost", "log", "run_dir", "summary"]


def run_dir() -> Path | None:
    value = os.environ.get("LAB_RUN_DIR")
    return Path(value) if value else None


def _emit(kind: str, **fields) -> None:
    directory = run_dir()
    if directory is not None:
        events.append(directory, kind, **fields)


def _check(metrics: dict) -> dict:
    if clash := events.RESERVED & metrics.keys():
        raise ValueError(f"metric names {sorted(clash)} are reserved by lab; rename them")
    return metrics


def log(step: int | None = None, **metrics) -> None:
    _emit(events.POINT, step=step, **_check(metrics))


def summary(**metrics) -> None:
    _emit(events.SUMMARY, **_check(metrics))


def cost(usd: float, note: str = "") -> None:
    usd = float(usd)
    if not math.isfinite(usd):  # a NaN would poison every later spend total
        print(f"lab: ignored cost({usd}): not a number of dollars", file=sys.stderr)
        return
    _emit(events.COST, usd=usd, note=note)


def artifact(path: str | os.PathLike, title: str = "") -> None:
    directory = run_dir()
    if directory is None:
        return
    source = Path(path)
    folder = directory / "artifacts"
    folder.mkdir(exist_ok=True)
    target, n = folder / source.name, 2
    while target.exists() and target.resolve() != source.resolve():  # two files with one name: keep both
        target, n = folder / f"{source.stem}-{n}{source.suffix}", n + 1
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    events.append(directory, events.ARTIFACT, path=f"artifacts/{target.name}", title=title)
