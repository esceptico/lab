"""What "compare honestly" means, in one place. Pure functions over records; no IO.

Two runs are comparable when they ran against the same accepted eval: the same lock epoch, and
neither saw a changed locked/ that was not accepted. Deltas, the baseline and the best-so-far
line only ever use comparable runs.
"""

from collections.abc import Sequence
from enum import StrEnum

from .model import CampaignConfig, Run, Verdict


class Change(StrEnum):
    BETTER = "better"
    WORSE = "worse"
    WITHIN_NOISE = "within_noise"


def comparable(a: Run, b: Run) -> bool:
    return a.lock.epoch == b.lock.epoch and a.lock.ok and b.lock.ok


def current_epoch(runs: Sequence[Run]) -> int:
    return max((r.lock.epoch for r in runs), default=1)


def delta(run: Run, parent: Run | None, metric: str) -> float | None:
    if parent is None or not comparable(run, parent):
        return None
    value, reference = run.value(metric), parent.value(metric)
    return None if value is None or reference is None else value - reference


LIKELY_REAL = 2.0  # a change of at least this many noise floors reads as likely real; under 1 as within noise


def noise_multiple(change: float | None, config: CampaignConfig) -> float | None:
    """How many noise floors a change spans; None without a change, or until the noise floor is measured."""
    return abs(change) / config.noise_floor if change is not None and config.noise_floor else None


def classify(change: float, config: CampaignConfig) -> Change:
    if abs(change) <= config.noise_floor:
        return Change.WITHIN_NOISE
    return Change.BETTER if config.better(change, 0.0) else Change.WORSE


def to_target(value: float, config: CampaignConfig) -> float | None:
    """How far a value still is from the campaign's target, in the better direction; 0 once reached."""
    if config.target is None:
        return None
    return max(config.target - value if config.goal == "max" else value - config.target, 0.0)


def baseline(runs: Sequence[Run], epoch: int = 0) -> Run | None:
    """The most recently kept run that ran on the current, unchanged eval. `epoch` is the campaign's accepted
    eval, which is newer than every run right after `lab lock --accept`: then nothing is comparable yet."""
    epoch = max(epoch, current_epoch(runs))
    kept = [r for r in runs if r.verdict is Verdict.KEEP and r.lock.epoch == epoch and r.lock.ok and r.verdict_at]
    return max(kept, key=lambda r: r.verdict_at, default=None)


def best_so_far(runs: Sequence[Run], metric: str) -> dict[str, float | None]:
    """For each run in order: the metric of the latest kept comparable run up to it (the staircase)."""
    line: dict[str, float | None] = {}
    epoch, current = None, None
    for run in runs:
        if run.lock.epoch != epoch:
            epoch, current = run.lock.epoch, None
        if run.verdict is Verdict.KEEP and run.lock.ok and (value := run.value(metric)) is not None:
            current = value
        line[run.id] = current
    return line


def spent(runs: Sequence[Run]) -> float:
    return sum(r.cost_usd for r in runs)


def gain(runs: Sequence[Run], baseline: Run | None, config: CampaignConfig) -> dict | None:
    """The baseline against the first comparable run of its epoch that reported the metric."""
    if baseline is None:
        return None
    first = next((r for r in runs if comparable(r, baseline) and r.value(config.metric) is not None), baseline)
    if first.id == baseline.id:  # the first result is the baseline: no gain yet
        return None
    change = delta(baseline, first, config.metric)
    return None if change is None else {"from": first.id, "delta": change}
