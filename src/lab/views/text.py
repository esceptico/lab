"""What the CLI prints: the board's content as text, for a person at a terminal and an agent reading a pipe.

A read command's `--json` and its text come from the same values, in the board's words: Kept, Reverted,
Inconclusive, Failed, Not judged, Running; Δ against the parent; a change of at least LIKELY_REAL noise
floors is likely real and is the only one coloured.
"""

import re
import shlex
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ..core import compare, findings
from ..core.model import CampaignConfig, Run, Status
from ..core.store import Campaign
from . import diff, term
from .summary import LABELS, summarize

MARKS = {"keep": ("●", "good"), "revert": ("○", "dim"), "inconclusive": ("◌", "dim"), "none": ("·", "dim"),
         "failed": ("✕", "bad"), "running": ("◉", "bold")}  # fmt: skip
LAST = 5  # runs `lab status` lists
EARLY = 2  # ancestors `lab show` lists before folding the rest into one line
CELL = 32  # columns a compared value gets on a terminal; lab show has it in full
MARKDOWN = re.compile(r"\*\*|__|`|\[([^\]]+)\]\([^)]*\)")


def kind(s: dict) -> str:
    return "running" if s["status"] == "running" else s["verdict"] or ("failed" if s["status"] == "failed" else "none")


def mark(k: str) -> str:
    glyph, role = MARKS[k]
    return term.paint(glyph, role)


def rounded(value: float, config: CampaignConfig) -> Decimal:
    """Halves round up, as the board's toFixed does, so 0.8125 reads 0.813 in both places."""
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-config.fmt), rounding=ROUND_HALF_UP)


def num(value: float | None, config: CampaignConfig) -> str:
    return "-" if value is None else f"{rounded(value, config)}"


def signed(change: float | None, config: CampaignConfig) -> str:
    if change is None:
        return ""
    value = rounded(change, config)
    return f"±{abs(value)}" if value == 0 else f"{value:+}"


def tone(change: float | None, config: CampaignConfig) -> str:
    """good or bad for a likely-real change, nothing otherwise: colour only means something real."""
    x = compare.noise_multiple(change, config)
    if x is None or x < compare.LIKELY_REAL:
        return ""
    return "good" if config.better(change, 0.0) else "bad"


def strength(change: float, config: CampaignConfig) -> str:
    """'better, 12.7× noise, likely real' / 'worse, 0.3× noise, within noise' / 'worse, noise floor not set'."""
    direction = "better" if config.better(change, 0.0) else "worse" if change else "no change"
    x = compare.noise_multiple(change, config)
    if x is None:
        return f"{direction}, noise floor not set"
    word = "likely real" if x >= compare.LIKELY_REAL else "marginal" if x >= 1 else "within noise"
    return f"{direction}, {x:.1f}× noise, {word}"


def shift(change: float, config: CampaignConfig) -> str:
    return term.paint(signed(change, config), tone(change, config))


def change_cell(change: float | None, config: CampaignConfig) -> str:
    if change is None:
        return ""
    x = compare.noise_multiple(change, config)
    return shift(change, config) + (f" ({x:.1f}×)" if x is not None else "")


def verdict_word(s: dict, baseline: Run | None) -> str:
    k = kind(s)
    word = "Lost, judge it to close it" if s["lost"] else LABELS[k]
    if baseline and s["id"] == baseline.id:
        word += ", baseline"
    if s["status"] == "failed" and k != "failed":
        word += " (failed)"  # judged, though the command itself failed
    if not s["comparable"]:
        word += ", eval changed"
    return word


def plain(text: str) -> str:
    """findings.md bullets without their Markdown marks, for a terminal."""
    return MARKDOWN.sub(lambda m: m[1] or "", text)


def home(text: str) -> str:
    return text.replace(str(Path.home()), "~")


# ---------- lab status ----------


def earlier_keep(runs: list[Run], config: CampaignConfig) -> dict | None:
    """With nothing kept on the current eval: the last run kept under an earlier one, so 'none' is not misread."""
    kept = [r for r in runs if r.verdict == "keep" and r.value(config.metric) is not None]
    return {"run": kept[-1].id, "value": kept[-1].value(config.metric), "lock": kept[-1].lock.epoch} if kept else None


def status_data(campaign: Campaign) -> dict:
    config, runs = campaign.config(), campaign.runs()
    by_id = {r.id: r for r in runs}
    rows = [summarize(r, by_id, config) for r in runs]
    best = compare.baseline(runs, campaign.epoch)
    up = compare.gain(runs, best, config)
    value = best.value(config.metric) if best else None
    counts = {k: sum(kind(s) == k for s in rows) for k in MARKS}
    return {
        "campaign": campaign.name,
        "question": config.question,
        "metric": config.metric,
        "goal": config.goal,
        "noise_floor": config.noise_floor or None,
        "best": {"run": best.id, "experiment": best.experiment, "value": value} if best else None,
        "kept_earlier": None if best else earlier_keep(runs, config),
        "gain": {"from": up["from"], "delta": up["delta"], "x_noise": compare.noise_multiple(up["delta"], config)}
        if up
        else None,
        "target": config.target,
        "to_target": compare.to_target(value, config) if value is not None else None,
        "spent_usd": float(round(compare.spent(runs), 2)),
        "budget_usd": config.budget_usd,
        "runs": len(runs),
        "counts": {k: v for k, v in counts.items() if v},
        "running": [s["id"] for s in rows if kind(s) == "running"],
        "last_run": rows[-1]["started"] if rows else None,
        "next": [
            {"text": plain(f.text), "runs": list(f.refs)} for f in findings.read(campaign.findings, findings.NEXT)
        ],
    }


def status(campaign: Campaign) -> str:
    d, config = status_data(campaign), campaign.config()
    state = (
        f"{len(d['running'])} running: {', '.join(d['running'])}"
        if d["running"]
        else f"idle, last run {d['last_run'] or '-'}"
    )
    lines = [f"{term.paint(d['campaign'], 'bold')}  {term.paint(state, 'dim')}"]
    if d["question"]:
        lines.append(term.wrap(d["question"]))
    facts = []
    arrow = "↓" if d["goal"] == "min" else "↑"
    noise = f" · noise ±{num(d['noise_floor'], config)}" if d["noise_floor"] else " · noise not set"
    if b := d["best"]:
        best = f"{term.paint(num(b['value'], config), 'bold')}  {b['run']} {b['experiment']}"
    elif e := d["kept_earlier"]:
        best = f"none under eval lock {campaign.epoch} ({e['run']} {num(e['value'], config)} under lock {e['lock']})"
    else:
        best = "none yet"
    facts.append(("Best kept", f"{best} · {d['metric']} {arrow}{noise}"))
    if g := d["gain"]:
        since = f"since {g['from']}, the first result on this eval · {strength(g['delta'], config)}"
        facts.append(("Change", f"{shift(g['delta'], config)} {since}"))
    if d["target"] is not None:
        left = d["to_target"]
        reach = (
            "no kept result on this eval" if left is None else "reached" if left == 0 else f"{num(left, config)} to go"
        )
        facts.append(("Target", f"{num(d['target'], config)} · {reach}"))
    cap = d["budget_usd"]
    facts.append(
        ("Spend", f"${d['spent_usd']:.2f}" + (f" of ${cap:.2f} ({d['spent_usd'] / cap:.0%})" if cap else " (no cap)"))
    )
    facts.append(("Runs", f"{d['runs']}" + "".join(f" · {n} {LABELS[k].lower()}" for k, n in d["counts"].items())))
    lines += ["", term.pairs(facts)]
    if d["next"]:
        lines += ["", term.paint("Next", "bold")]
        for i, item in enumerate(d["next"], 1):
            refs = term.paint(f" ({', '.join(item['runs'])})", "dim") if item["runs"] else ""
            lines.append(f"  {i}. " + term.wrap(item["text"], 5) + refs)
    if d["runs"]:
        lines += [
            "",
            term.paint("Last run" if d["runs"] == 1 else f"Last {min(LAST, d['runs'])} runs", "bold"),
            ls(campaign, last=LAST),
        ]
    return "\n".join(lines)


def campaigns(lab) -> str:
    rows = []
    for campaign in lab.campaigns():
        d = status_data(campaign)
        best = f"{num(d['best']['value'], campaign.config())} {d['best']['run']}" if d["best"] else ""
        rows.append([campaign.name, str(d["runs"]), best, d["last_run"] or "", d["question"]])
    if not rows:
        return 'no campaigns yet: lab new campaign <name> --metric <metric> --goal min|max --question "..."'
    return term.table(["campaign", "runs", "best", "last run", "question"], rows, right=frozenset({1}), flex=4)


# ---------- lab ls ----------


def tree(runs: list[Run]) -> list[tuple[Run, int]]:
    """Runs in lineage order with a depth that steps in only where a parent has several children."""
    by_id = {r.id: r for r in runs}
    kids = {r.id: [k for k in runs if k.parent == r.id] for r in runs}
    out: list[tuple[Run, int]] = []

    def walk(run: Run, depth: int) -> None:
        out.append((run, depth))
        for child in kids[run.id]:
            walk(child, depth + (len(kids[run.id]) > 1))

    for root in (r for r in runs if r.parent not in by_id):
        walk(root, 0)
    return out


def ls_rows(runs: list[Run], config: CampaignConfig, verdict: str | None, exp: str | None) -> dict[str, dict]:
    by_id = {r.id: r for r in runs}
    rows = (summarize(r, by_id, config) for r in runs)
    return {s["id"]: s for s in rows if (verdict is None or kind(s) == verdict) and (exp is None or s["exp"] == exp)}


def record(run: Run, s: dict, best: Run | None, config: CampaignConfig) -> dict:
    """One run as `lab ls --json` gives it and piped `lab ls` prints it."""
    return {"id": run.id, "experiment": s["exp"], "parent": s["parent"], "lock": run.lock.epoch,
            "status": "lost" if s["lost"] else str(run.status), "verdict": s["verdict"], "value": s["value"],
            "delta": s["delta"], "x_noise": compare.noise_multiple(s["delta"], config), "cost_usd": s["cost"],
            "eval_changed": not s["comparable"], "baseline": best is not None and run.id == best.id,
            "hypothesis": s["hyp"]}  # fmt: skip


def ls(
    campaign: Campaign,
    verdict: str | None = None,
    exp: str | None = None,
    last: int | None = None,
    lineage: bool = False,
) -> str:
    """On a terminal: one line per run in the board's words. Piped: one fact per tab-separated column."""
    config, runs = campaign.config(), campaign.runs()
    best = compare.baseline(runs, campaign.epoch)
    rows = ls_rows(runs, config, verdict, exp)
    order = [(r, d) for r, d in (tree(runs) if lineage else [(r, 0) for r in runs]) if r.id in rows]
    if last:
        order = order[-last:]
    if not order:
        return "no runs match" if runs else f"no runs in {campaign.name} yet"
    if not term.terminal():
        head = ["run", "exp", "parent", "lock", "status", "verdict", "baseline", "result", "delta", "x_noise", "cost", "hypothesis"]  # fmt: skip
        body = []
        for run, _ in order:
            r = record(run, rows[run.id], best, config)
            body.append([r["id"], r["experiment"], r["parent"] or "", f"{r['lock']}" + (" changed" if r["eval_changed"] else ""),
                         r["status"], LABELS[r["verdict"] or "none"], "yes" if r["baseline"] else "",
                         "" if r["value"] is None else num(r["value"], config), signed(r["delta"], config),
                         "" if r["x_noise"] is None else f"{r['x_noise']:.1f}",
                         f"{r['cost_usd']:.2f}" if r["cost_usd"] else "", r["hypothesis"]])  # fmt: skip
        return term.table(head, body)
    body: list[list[str]] = []
    epoch = None
    for run, depth in order:
        s = rows[run.id]
        if not lineage and epoch is not None and run.lock.epoch != epoch:
            body.append([f"eval lock {run.lock.epoch} · not comparable with the runs above"])
        epoch = run.lock.epoch
        run_id = term.paint(run.id, "bold") if best and run.id == best.id else run.id
        body.append([mark(kind(s)), run_id, "  " * depth + s["exp"], num(s["value"], config),
                     change_cell(s["delta"], config), verdict_word(s, best),
                     f"${s['cost']:.2f}" if s["cost"] else "", s["hyp"]])  # fmt: skip
    head = ["", "run", "exp", "result", "Δ parent", "verdict", "cost", "hypothesis"]
    return term.table(head, body, right=frozenset({3, 4, 6}), flex=len(head) - 1)


def ls_data(campaign: Campaign, verdict: str | None = None, exp: str | None = None, last: int | None = None) -> dict:
    config, runs = campaign.config(), campaign.runs()
    best = compare.baseline(runs, campaign.epoch)
    rows = ls_rows(runs, config, verdict, exp)
    picked = [r for r in runs if r.id in rows]
    picked = picked[-last:] if last else picked
    return {"campaign": campaign.name, "metric": config.metric,
            "runs": [record(r, rows[r.id], best, config) for r in picked]}  # fmt: skip


# ---------- lab show ----------


def size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1024**2 else f"{n / 1024**2:.1f} MB"


def changes_summary(changes: diff.Changes) -> str:
    parts = []
    if changes.command:
        parts.append("command changed")
    if changes.diff:
        files, current = {}, None
        for line in changes.diff.splitlines():
            if line.startswith("@@ "):
                current = line[3:]
                files[current] = [0, 0]
            elif current and line.startswith("+"):
                files[current][0] += 1
            elif current and line.startswith("-"):
                files[current][1] += 1
        parts += [
            f"{name} {term.paint(f'+{a}', 'good')} {term.paint(f'-{d}', 'bad')}" for name, (a, d) in files.items()
        ]
    return " · ".join(parts) or "same code and command"


def lineage_lines(run: Run, by_id: dict[str, Run], config: CampaignConfig) -> list[str]:
    chain, node = [], by_id.get(run.parent or "")
    while node:
        chain.insert(0, node)
        node = by_id.get(node.parent or "")
    early, chain = chain[:-EARLY], chain[-EARLY:]
    kids = [r for r in by_id.values() if r.parent == run.id]

    rows = [(r, "  ") for r in chain] + [(run, "  ")] + [(k, "    ") for k in kids]
    pad = max(len(indent + r.experiment) for r, indent in rows)

    def line(r: Run, indent: str) -> str:
        s = summarize(r, by_id, config)
        text = f"{indent}{mark(kind(s))} {r.id}  {(indent + r.experiment)[len(indent) :]:<{pad - len(indent)}}  {num(s['value'], config):>7}"
        return term.paint(text + "  ← this run", "bold") if r is run else text

    out = [term.paint(f"  · {len(early)} earlier, from {early[0].id}", "dim")] if early else []
    return out + [line(r, indent) for r, indent in rows]


def show(campaign: Campaign, run: Run) -> str:
    config, runs = campaign.config(), campaign.runs()
    by_id = {r.id: r for r in runs}
    s, best = summarize(run, by_id, config), compare.baseline(runs, campaign.epoch)
    parent = by_id.get(run.parent or "")
    lines = [f"{mark(kind(s))} {term.paint(run.id, 'bold')}  {run.experiment}  {verdict_word(s, best)}"]
    result = term.paint(num(s["value"], config), "bold") if s["value"] is not None else "no result"
    if s["delta"] is not None:
        result += f"  {shift(s['delta'], config)} vs {parent.id} · {strength(s['delta'], config)}"
    elif parent and parent.lock.epoch != run.lock.epoch:
        result += f"  vs {parent.id}: other eval lock"
    bv = best.value(config.metric) if best and best.id not in (run.id, run.parent) else None
    if bv is not None and s["value"] is not None:
        result += term.paint(f" · {signed(s['value'] - bv, config)} vs best {best.id}", "dim")
    meta = [s["started"], f"ran {duration(s['dur'])}" if s["dur"] is not None else "", f"${s['cost']:.2f}" if s["cost"] else "",
            run.host or run.backend, f"eval lock {run.lock.epoch}" + ("" if run.lock.ok else ", changed")]  # fmt: skip
    lines += [result, term.paint(" · ".join(m for m in meta if m), "dim"), ""]
    claim = [("Hypothesis", run.hypothesis or "-"), ("Predicted", run.prediction or "-"), ("Verdict", s["note"] or "-")]
    if run.tags:
        claim.append(("Tags", ", ".join(run.tags)))
    lines += [term.pairs(claim), "", term.paint("Lineage", "bold"), *lineage_lines(run, by_id, config), ""]
    run_dir = campaign.run_dir(run.id)
    files = [p for p in sorted(run_dir.iterdir()) if p.name != ".lock"] + [run_dir / a.path for a in run.artifacts]
    names = [f"{p.relative_to(run_dir)} {term.paint(size(p.stat().st_size), 'dim')}" for p in files if p.is_file()]
    facts = [("Folder", str(run_dir.relative_to(campaign.root.parent.parent)) + "/"), ("Files", " · ".join(names) or "-"),
             ("Command", home(shlex.join(run.command)))]  # fmt: skip
    if parent:
        facts.append((f"vs {parent.id}", changes_summary(diff.between(campaign, parent, run))))
    lines.append(term.pairs(facts))
    return "\n".join(lines)


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


# ---------- lab compare ----------

GROUP = dict.fromkeys(("verdict", "delta parent", "parent", "experiment", "hypothesis"), "Run") | dict.fromkeys(
    ("backend", "host", "duration", "cost", "eval lock", "lib/", "tags"), "Setup"
)  # in attr() order; the command has its own section


def compare_data(campaign: Campaign, a: Run, b: Run) -> dict:
    config, runs = campaign.config(), campaign.runs()
    by_id = {r.id: r for r in runs}
    sa, sb = summarize(a, by_id, config), summarize(b, by_id, config)
    comparable = compare.comparable(a, b)
    change = sa["value"] - sb["value"] if comparable and None not in (sa["value"], sb["value"]) else None
    metrics = [
        k
        for k in dict.fromkeys([config.metric, *a.metrics, *b.metrics])
        if a.value(k) is not None or b.value(k) is not None
    ]

    def attr(r: Run, s: dict) -> dict:
        return {"verdict": LABELS[kind(s)], "delta parent": signed(s["delta"], config), "parent": r.parent or "",
                "experiment": r.experiment, "hypothesis": r.hypothesis, "backend": r.backend, "host": r.host,
                "duration": duration(r.duration_s) if r.duration_s is not None else "",
                "cost": f"{r.cost_usd:.2f}" if r.cost_usd else "", "eval lock": f"{r.lock.epoch} · {r.lock.hash[:8]}",
                "lib/": (r.lib_hash or "")[:8], "command": home(shlex.join(r.command)), "tags": ", ".join(r.tags)}  # fmt: skip

    ta, tb = attr(a, sa), attr(b, sb)
    linked = a.parent == b.id or b.parent == a.id
    if linked:  # code is diffed parent → child
        changes = diff.between(campaign, *((b, a) if a.parent == b.id else (a, b)))
    else:  # any other pair: the command only, B → A
        changes = diff.Changes((shlex.join(b.command), shlex.join(a.command)) if a.command != b.command else None, None)
    return {
        "a": {"id": a.id, "experiment": a.experiment, "value": sa["value"], "verdict": sa["verdict"]},
        "b": {"id": b.id, "experiment": b.experiment, "value": sb["value"], "verdict": sb["verdict"]},
        "delta": change,
        "x_noise": compare.noise_multiple(change, config),
        "comparable": comparable,
        "metrics": [{"name": k, "a": a.value(k), "b": b.value(k)} for k in metrics],
        "attributes": [{"name": k, "a": ta[k], "b": tb[k]} for k in ta],
        "changes": {"command": changes.command, "diff": changes.diff, "parent_and_child": linked},
    }


def compare_text(campaign: Campaign, a: Run, b: Run, everything: bool = False) -> str:
    config, d, on = campaign.config(), compare_data(campaign, a, b), term.terminal()
    lines = [f"A {term.paint(a.id, 'bold')} {a.experiment}   B {term.paint(b.id, 'bold')} {b.experiment}"]
    if d["delta"] is not None:
        lines.append(f"A − B  {shift(d['delta'], config)} {config.metric} · {strength(d['delta'], config)}")
    else:
        lines.append(
            "A − B  -, " + ("they ran on different eval locks" if not d["comparable"] else "one has no result")
        )
    arrow = "↓" if config.goal == "min" else "↑"
    metrics, attrs, same = [], [], 0
    for m in d["metrics"]:  # only the campaign metric has a known direction, so only its Δ is coloured
        if not everything and m["a"] == m["b"]:
            same += 1
            continue
        key = m["name"] == config.metric
        change = m["a"] - m["b"] if None not in (m["a"], m["b"]) and d["comparable"] else None
        delta = term.paint(signed(change, config), tone(change, config) if key else "") if change is not None else ""
        metrics.append((m["name"], arrow if key else "", num(m["a"], config) if m["a"] is not None else "",
                        num(m["b"], config) if m["b"] is not None else "", delta))  # fmt: skip
    for x in d["attributes"]:
        if x["name"] not in GROUP:
            continue
        if everything or x["a"] != x["b"]:
            attrs.append((GROUP[x["name"]], x["name"], x["a"], x["b"]))
        else:
            same += 1
    if on:

        def shown(name: str, v: str) -> str:
            return ("$" + v if name == "cost" and v else v) or "-"

        if metrics:
            lines += [
                "",
                term.table(
                    ["metric", a.id, b.id, "Δ"],
                    [[f"{n} {d_}".strip(), va or "-", vb or "-", dd] for n, d_, va, vb, dd in metrics],
                    right=frozenset({1, 2, 3}),
                ),
            ]
        if attrs:
            lines += [
                "",
                term.table(
                    ["", a.id, b.id],
                    [
                        [
                            "Δ parent" if n == "delta parent" else n,
                            term.cut(shown(n, va), CELL),
                            term.cut(shown(n, vb), CELL),
                        ]
                        for _, n, va, vb in attrs
                    ],
                ),
            ]
    else:  # one table: a group column, and every value raw (empty when missing, no units)
        rows = [["metrics", n, d_, va, vb, dd] for n, d_, va, vb, dd in metrics] + [
            [g.lower(), n, "", va, vb, ""] for g, n, va, vb in attrs
        ]
        lines += ["", term.table(["group", "field", "dir", a.id, b.id, "delta"], rows)]
    if same and not everything:
        lines.append(term.paint(f"{same} attributes are the same; --all shows them", "dim"))
    lines += ["", *changes_text(d["changes"], a, b)]
    return "\n".join(lines)


def changes_text(changes: dict, a: Run, b: Run) -> list[str]:
    out = []
    if changes["command"]:
        out += [term.paint("Command", "bold"), *command_change(*changes["command"])]
    if changes["diff"]:
        roles = {"+": "good", "-": "bad", "@": "dim"}
        out += ["", term.paint("Code", "bold")] if out else [term.paint("Code", "bold")]
        out += [term.paint(line, roles.get(line[:1], "")) for line in changes["diff"].splitlines()]
    if not changes["parent_and_child"]:
        out += ([""] if out else []) + [
            term.paint(
                f"Code is diffed between a parent and its child only: lab show {a.id} and lab show {b.id} have each run's change.",
                "dim",
            )
        ]
    elif not out:
        out = ["Same code and command."]
    return out


def command_change(before: str, after: str) -> list[str]:
    """Only the words that changed, with a word of context on each side: a long command differs in one flag."""
    old, new = home(before).split(" "), home(after).split(" ")
    i = 0
    while i < min(len(old), len(new)) and old[i] == new[i]:
        i += 1
    j = 0
    while j < min(len(old), len(new)) - i and old[-1 - j] == new[-1 - j]:
        j += 1
    lead = "… " if i > 1 else " ".join(old[:i]) + " " if i else ""
    tail = " …" if j > 1 else " " + " ".join(old[len(old) - j :]) if j else ""
    context = (" ".join(old[i - 1 : i]) + " ") if i > 1 else ""
    removed, added = " ".join(old[i : len(old) - j]), " ".join(new[i : len(new) - j])
    return [term.paint(f"{sign} {lead}{context}{words}{tail}", role)
            for sign, words, role in (("-", removed, "bad"), ("+", added, "good")) if words]  # fmt: skip


# ---------- lab budget, verdict, run ----------


def budget_data(campaign: Campaign) -> dict:
    runs, cap = campaign.runs(), campaign.config().budget_usd
    return {
        "spent_usd": float(round(compare.spent(runs), 2)),
        "budget_usd": cap,
        "runs": [{"id": r.id, "experiment": r.experiment, "cost_usd": r.cost_usd} for r in runs if r.cost_usd],
    }


def budget(campaign: Campaign) -> str:
    d = budget_data(campaign)
    cap, spent = d["budget_usd"], d["spent_usd"]
    if not term.terminal():  # one table: the bills, then the total and the cap as rows
        rows = [[r["id"], r["experiment"], f"{r['cost_usd']:.2f}"] for r in d["runs"]]
        rows += [["total", "", f"{spent:.2f}"], ["budget", "", f"{cap:.2f}" if cap else ""]]
        return term.table(["run", "exp", "cost_usd"], rows)
    head = f"${spent:.2f}" + (f" of ${cap:.2f} ({spent / cap:.0%})" if cap else " recorded (no cap)")
    lines = [term.paint(head, "bold")]
    if d["runs"]:
        rows = [[r["id"], r["experiment"], f"${r['cost_usd']:.2f}"] for r in d["runs"]]
        lines.append(term.table(["run", "exp", "cost"], rows, right=frozenset({2})))
    return "\n".join(lines)


def verdict_line(campaign: Campaign, run: Run, before: Run | None, after: Run | None) -> str:
    config = campaign.config()
    line = f"{run.id} {LABELS[str(run.verdict)]}"
    if after is None:
        return line + " · no baseline yet"
    if before is None or before.id == after.id:
        return line + f" · baseline {after.id}" + ("" if after.id == run.id else " (unchanged)")
    change = compare.delta(after, before, config.metric)
    extra = f" ({signed(change, config)} vs {before.id}, {strength(change, config)})" if change is not None else ""
    return line + f" · baseline {before.id} → {after.id}{extra}"


def result_line(campaign: Campaign, run: Run) -> str:
    config = campaign.config()
    parts = [f"{run.id} {run.status} in {duration(run.duration_s)}"]
    value = run.value(config.metric)
    if value is not None:
        parts.append(f"{config.metric} {term.paint(num(value, config), 'bold')}")
        best = campaign.baseline()
        if best and best.id != run.id and (change := compare.delta(run, best, config.metric)) is not None:
            parts.append(f"{shift(change, config)} vs baseline {best.id}, {strength(change, config)}")
    elif run.status is Status.OK:
        parts.append(f"no {config.metric} reported: log it with lab.summary({config.metric}=...)")
    if run.cost_usd:
        parts.append(f"${run.cost_usd:.2f}")
    return " · ".join(parts)
