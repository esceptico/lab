# lab.fig reference

Generated from the code by `scripts/skill_reference.py`; if this disagrees with `lab <cmd> --help`, the CLI wins.


Figures as data: each call writes a JSON spec into the run, and the board, reports and blog
embeds all draw it with the same renderer. Outside `lab run` the spec is only returned.

    from lab import fig
    fig.line({"trained": S, "random-init": S0}, log_y=True, mark_x=(8.5, "top 8 ablated"),
             x_label="singular index", title="Trained Jacobians concentrate")

Every function also takes title, sub, caption, source (run ids; defaults to this run) and name
(the file stem; defaults to a slug of the title). Values can be lists, numpy arrays or tensors;
NaN becomes a gap. Axis and colour ranges default to the data unless `domain` is given.

## fig.bars

```python
fig.bars(categories: Sequence[str], series: Mapping[str, Any], *, domain: tuple[float, float] | None = None, fmt: int = 1, **common: Unpack[lab.fig.Common]) -> dict
```

Horizontal grouped bars: one group per category, one bar per series. With intervals, prefer dots.

```python
fig.bars(["GPQA", "MMLU-Pro"], {"zero-shot": [41.2, 62.0], "tuned": [49.1, 69.8]}, title="Accuracy (%)")
```

## fig.dots

```python
fig.dots(items: Sequence[Mapping | tuple], *, x_label: str = '', interval: str = '95% CI', reference: tuple[float, str] | tuple[float, str, float] | None = None, domain: tuple[float, float] | None = None, fmt: int = 2, **common: Unpack[lab.fig.Common]) -> dict
```

items: [(label, mean, lo, hi)] or [{"label", "mean", "lo", "hi", "highlight"}]; `interval` names what lo–hi is.
reference: (value, label) or (value, label, noise) drawn as a rule with a band.

```python
fig.dots([("Random dirs", 0.03, 0.01, 0.05), {"label": "Jacobian k=8", "mean": 0.47, "lo": 0.44, "hi": 0.50, "highlight": True}],
         reference=(0.03, "random", 0.02), x_label="refusal drop", title="Bases vs control")
```

## fig.heatmap

```python
fig.heatmap(z: Any, *, x: Sequence[str], y: Sequence[str], diverging: bool = False, domain: tuple[float, float] | None = None, value_label: str = 'value', annotate: tuple[int, int, str] | None = None, fmt: int = 2, **common: Unpack[lab.fig.Common]) -> dict
```

z: rows × columns (e.g. layers × tokens). `diverging` centres the colours on 0; `annotate`=(row, col, label) boxes a cell.

```python
fig.heatmap(effect, x=tokens, y=[f"L{i}" for i in range(n_layers)], diverging=True,
            value_label="recovered", annotate=(13, 6, "L13 · bomb"), title="Patching")
```

## fig.hist

```python
fig.hist(series: Mapping[str, Any], *, x_label: str = '', bins: int = 40, domain: tuple[float, float] | None = None, **common: Unpack[lab.fig.Common]) -> dict
```

series: {name: raw values}, binned when drawn.

```python
fig.hist({"harmful": proj_a, "harmless": proj_b}, x_label="projection", bins=40, title="Separation")
```

## fig.line

```python
fig.line(series: Mapping[str, Any], *, x: Sequence[float] | None = None, x_label: str = '', log_y: bool = False, log_x: bool = False, mark_x: float | tuple[float, str] | None = None, y_fmt: int | None = None, domain: tuple[float, float] | None = None, **common: Unpack[lab.fig.Common]) -> dict
```

series: {name: ys} or {name: {"y": ys, "lo": lo, "hi": hi, "muted": bool}}. x defaults to 0, 1, 2, …

```python
fig.line({"trained": S, "random-init": S0}, log_y=True, mark_x=(8.5, "top 8 ablated"),
         x_label="singular index", title="Trained Jacobians concentrate", caption="...")
```

## fig.multiples

```python
fig.multiples(panels: Mapping[str, Mapping[str, Any]], *, x: Sequence[float], x_label: str = '', log_x: bool = False, highlight: str | None = None, muted: Sequence[str] = (), y_fmt: int | None = None, domain: tuple[float, float] | None = None, **common: Unpack[lab.fig.Common]) -> dict
```

panels: {panel title: {series name: ys or {"y", "lo", "hi"}}}, drawn as small line charts on one y scale.

```python
fig.multiples({"layers 10→16": {"J": y1, "random": r1}, "layers 14→24": {"J": y2, "random": r2}},
              x=[1, 2, 4, 8, 16, 32], log_x=True, muted=["random"], highlight="layers 14→24", title="Drop vs k")
```

## fig.reliability

```python
fig.reliability(series: Mapping[str, tuple[Any, Any]], *, bins: int = 10, **common: Unpack[lab.fig.Common]) -> dict
```

series: {name: (confidence, correct)} as raw per-item arrays; bins and ECE are computed here.

```python
fig.reliability({"zero-shot": (conf0, correct0), "tuned": (conf1, correct1)}, title="Calibration")
```

## fig.scatter

```python
fig.scatter(groups: Mapping[str, Any], *, x_label: str = 'x', y_label: str = 'y', **common: Unpack[lab.fig.Common]) -> dict
```

groups: {name: N×2 points}. Past three groups the colours repeat, so fold extras into one.

```python
fig.scatter({"harmful": pts_a, "harmless": pts_b}, x_label="PC 1", y_label="PC 2", title="Layer 20 PCA")
```

## fig.table

```python
fig.table(rows: Sequence[Mapping], *, columns: Sequence[Mapping] | None = None, reference: float | None = None, domain: tuple[float, float] | None = None, fmt: int = 2, **common: Unpack[lab.fig.Common]) -> dict
```

columns: [{"key", "label", "kind": text|num|bar|delta|run|money, "lo", "hi", "fmt", "optional"}].
A "bar" column draws an inline bar, with a whisker when lo/hi keys are given.

```python
fig.table(rows, columns=[{"key": "label", "label": "Basis"},
    {"key": "mean", "label": "Drop", "kind": "bar", "lo": "lo", "hi": "hi"},
    {"key": "run", "label": "Run", "kind": "run"}], reference=0.03, title="Results")
```

## fig.tokens

```python
fig.tokens(rows: Sequence[tuple[str, Sequence[str], Any]], *, diverging: bool = True, domain: tuple[float, float] | None = None, value_label: str = 'value', fmt: int = 2, **common: Unpack[lab.fig.Common]) -> dict
```

rows: [(label, tokens, values), ...], one shaded strip of text per row.

```python
fig.tokens([("harmful", toks_a, proj_a), ("harmless", toks_b, proj_b)], value_label="projection",
           title="What the top direction reads")
```
