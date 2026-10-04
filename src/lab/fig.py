"""Figures as data: each call writes a JSON spec into the run, and the board, reports and blog
embeds all draw it with the same renderer. Outside `lab run` the spec is only returned.

    from lab import fig
    fig.line({"trained": S, "random-init": S0}, log_y=True, mark_x=(8.5, "top 8 ablated"),
             x_label="singular index", title="Trained Jacobians concentrate")

Every function also takes title, sub, caption, source (run ids; defaults to this run) and name
(the file stem; defaults to a slug of the title). Values can be lists, numpy arrays or tensors;
NaN becomes a gap. Axis and colour ranges default to the data unless `domain` is given.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict, Unpack

from . import events, run_dir
from .stats import reliability_bins

__all__ = ["bars", "dots", "heatmap", "hist", "line", "multiples", "reliability", "scatter", "table", "tokens"]

Range = tuple[float, float]


class Common(TypedDict, total=False):
    title: str
    sub: str
    caption: str
    source: Sequence[str]
    name: str


def _emit(kind: str, common: Common, **fields) -> dict:
    spec = {"type": kind, **{k: v for k, v in common.items() if k != "name"}, **fields}
    spec = {k: events.plain(v) for k, v in spec.items() if v is not None and v != "" and v is not False}
    directory = run_dir()
    if directory is None:
        return spec
    spec.setdefault("source", [directory.name])
    folder = directory / "figures"
    folder.mkdir(exist_ok=True)
    stem = common.get("name") or re.sub(r"[^a-z0-9]+", "-", spec.get("title", kind).lower()).strip("-")[:60] or kind
    for n in range(1, 1000):
        path = folder / (f"{stem}.json" if n == 1 else f"{stem}-{n}.json")
        try:
            with open(path, "x") as f:  # "x" claims the name atomically, so parallel writers never collide
                json.dump(spec, f)
            break
        except FileExistsError:
            continue
    events.append(directory, events.FIGURE, path=f"figures/{path.name}", title=spec.get("title", ""), type=kind)
    return spec


def _series(data: Mapping[str, Any]) -> list[dict]:
    return [{"name": k, **v} if isinstance(v, Mapping) else {"name": k, "y": v} for k, v in data.items()]


def line(
    series: Mapping[str, Any],
    *,
    x: Sequence[float] | None = None,
    x_label: str = "",
    log_y: bool = False,
    log_x: bool = False,
    mark_x: float | tuple[float, str] | None = None,
    y_fmt: int | None = None,
    domain: Range | None = None,
    **common: Unpack[Common],
) -> dict:
    """series: {name: ys} or {name: {"y": ys, "lo": lo, "hi": hi, "muted": bool}}. x defaults to 0, 1, 2, …"""
    items = _series(series)
    mark = mark_x if isinstance(mark_x, tuple) else (mark_x, "") if mark_x is not None else None
    return _emit(
        "line", common,
        series=items, x=x if x is not None else list(range(max(len(s["y"]) for s in items))),
        xLabel=x_label, logY=log_y, logX=log_x, yFmt=y_fmt, domain=domain,
        markX={"x": mark[0], "label": mark[1]} if mark else None,
    )  # fmt: skip


def heatmap(
    z: Any,
    *,
    x: Sequence[str],
    y: Sequence[str],
    diverging: bool = False,
    domain: Range | None = None,
    value_label: str = "value",
    annotate: tuple[int, int, str] | None = None,
    fmt: int = 2,
    **common: Unpack[Common],
) -> dict:
    """z: rows × columns (e.g. layers × tokens). `diverging` centres the colours on 0; `annotate`=(row, col, label) boxes a cell."""
    return _emit(
        "heatmap", common,
        z=z, xLabels=[str(v) for v in x], yLabels=[str(v) for v in y], diverging=diverging, domain=domain,
        valueLabel=value_label, fmt=fmt,
        annotate={"row": annotate[0], "col": annotate[1], "label": annotate[2]} if annotate else None,
    )  # fmt: skip


def tokens(
    rows: Sequence[tuple[str, Sequence[str], Any]],
    *,
    diverging: bool = True,
    domain: Range | None = None,
    value_label: str = "value",
    fmt: int = 2,
    **common: Unpack[Common],
) -> dict:
    """rows: [(label, tokens, values), ...], one shaded strip of text per row."""
    items = [{"label": label, "tokens": list(toks), "values": values} for label, toks, values in rows]
    return _emit("tokens", common, rows=items, diverging=diverging, domain=domain, valueLabel=value_label, fmt=fmt)


def dots(
    items: Sequence[Mapping | tuple],
    *,
    x_label: str = "",
    interval: str = "95% CI",
    reference: tuple[float, str] | tuple[float, str, float] | None = None,
    domain: Range | None = None,
    fmt: int = 2,
    **common: Unpack[Common],
) -> dict:
    """items: [(label, mean, lo, hi)] or [{"label", "mean", "lo", "hi", "highlight"}]; `interval` names what lo–hi is.
    reference: (value, label) or (value, label, noise) drawn as a rule with a band."""
    rows = [
        dict(i) if isinstance(i, Mapping) else dict(zip(("label", "mean", "lo", "hi"), i, strict=True)) for i in items
    ]
    ref = (
        {"value": reference[0], "label": reference[1], "noise": reference[2] if len(reference) > 2 else 0}
        if reference
        else None
    )
    return _emit("dots", common, items=rows, xLabel=x_label, interval=interval, reference=ref, domain=domain, fmt=fmt)


def scatter(groups: Mapping[str, Any], *, x_label: str = "x", y_label: str = "y", **common: Unpack[Common]) -> dict:
    """groups: {name: N×2 points}. Past three groups the colours repeat, so fold extras into one."""
    items = [{"name": k, "points": v} for k, v in groups.items()]
    return _emit("scatter", common, groups=items, xLabel=x_label, yLabel=y_label)


def hist(
    series: Mapping[str, Any],
    *,
    x_label: str = "",
    bins: int = 40,
    domain: Range | None = None,
    **common: Unpack[Common],
) -> dict:
    """series: {name: raw values}, binned when drawn."""
    items = [{"name": k, "values": v} for k, v in series.items()]
    return _emit("hist", common, series=items, xLabel=x_label, bins=bins, domain=domain)


def bars(
    categories: Sequence[str],
    series: Mapping[str, Any],
    *,
    domain: Range | None = None,
    fmt: int = 1,
    **common: Unpack[Common],
) -> dict:
    """Horizontal grouped bars: one group per category, one bar per series. With intervals, prefer dots."""
    items = [{"name": k, "values": v} for k, v in series.items()]
    return _emit("bars", common, categories=list(categories), series=items, domain=domain, fmt=fmt)


def reliability(series: Mapping[str, tuple[Any, Any]], *, bins: int = 10, **common: Unpack[Common]) -> dict:
    """series: {name: (confidence, correct)} as raw per-item arrays; bins and ECE are computed here."""
    items = []
    for label, (confidence, correct) in series.items():
        binned, ece = reliability_bins(events.plain(confidence), events.plain(correct), bins)
        items.append({"name": label, "ece": ece, "bins": binned})
    return _emit("reliability", common, series=items, nbins=bins)


def multiples(
    panels: Mapping[str, Mapping[str, Any]],
    *,
    x: Sequence[float],
    x_label: str = "",
    log_x: bool = False,
    highlight: str | None = None,
    muted: Sequence[str] = (),
    y_fmt: int | None = None,
    domain: Range | None = None,
    **common: Unpack[Common],
) -> dict:
    """panels: {panel title: {series name: ys or {"y", "lo", "hi"}}}, drawn as small line charts on one y scale."""
    out = [
        {
            "title": title,
            "highlight": title == highlight,
            "x": x,
            "series": [s | {"muted": s["name"] in muted} for s in _series(series)],
        }
        for title, series in panels.items()
    ]
    return _emit("multiples", common, panels=out, xLabel=x_label, logX=log_x, domain=domain, yFmt=y_fmt)


def table(
    rows: Sequence[Mapping],
    *,
    columns: Sequence[Mapping] | None = None,
    reference: float | None = None,
    domain: Range | None = None,
    fmt: int = 2,
    **common: Unpack[Common],
) -> dict:
    """columns: [{"key", "label", "kind": text|num|bar|delta|run|money, "lo", "hi", "fmt", "optional"}].
    A "bar" column draws an inline bar, with a whisker when lo/hi keys are given."""
    return _emit(
        "table", common, rows=[dict(r) for r in rows], columns=columns, reference=reference, domain=domain, fmt=fmt
    )
