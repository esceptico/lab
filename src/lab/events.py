"""The metrics.jsonl format: written inside a run, read back by the CLI. Standard library only.

One JSON object per line, with "t" (unix time) and "kind":
    point     {"step": int | null, <name>: value, ...}
    summary   {<name>: value, ...}
    cost      {"usd": float, "note": str}
    artifact  {"path": "artifacts/<file>", "title": str}
    figure    {"path": "figures/<name>.json", "title": str, "type": str}
"""

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

FILE = "metrics.jsonl"
POINT, SUMMARY, COST, ARTIFACT, FIGURE = "point", "summary", "cost", "artifact", "figure"
RESERVED = frozenset({"t", "kind", "step"})


def append(run_dir: Path, kind: str, **fields) -> None:
    line = json.dumps({"t": time.time(), "kind": kind, **{k: plain(v) for k, v in fields.items()}}, allow_nan=False)
    with open(run_dir / FILE, "a") as f:
        f.write(line + "\n")


def plain(value):
    """Numbers, arrays and tensors to JSON values; NaN and infinity become null."""
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


@dataclass
class Events:
    points: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    cost: float = 0.0
    artifacts: list[dict] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)

    def curve_keys(self) -> list[str]:
        keys: dict[str, None] = {}
        for point in self.points:
            for key, value in point.items():
                if key not in RESERVED and _number(value):
                    keys.setdefault(key)
        return list(keys)

    def curve(self, key: str) -> tuple[list, list]:
        """(steps, values); a point logged without a step takes its position."""
        rows = [
            (p["step"] if p.get("step") is not None else i, p[key])
            for i, p in enumerate(self.points)
            if _number(p.get(key))
        ]
        return [r[0] for r in rows], [r[1] for r in rows]


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read(path: Path) -> Events:
    events = Events()
    if not path.exists():
        return events
    last, explicit = {}, {}
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:  # a line cut off by a crash; the rest of the file still counts
            continue
        values = {k: v for k, v in record.items() if k not in RESERVED}
        match record.get("kind"):
            case "point":
                events.points.append(record)
                last.update(values)
            case "summary":
                explicit.update(values)
            case "cost":
                if isinstance(usd := record.get("usd"), (int, float)):  # an old null (NaN) cost counts as nothing
                    events.cost += usd
            case "artifact":
                events.artifacts.append(values)
            case "figure":
                events.figures.append(values)
    events.summary = {**last, **explicit}  # an explicit summary wins over the last point of a curve
    return events
