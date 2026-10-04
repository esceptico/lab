"""`lab report <campaign>`: a self-contained interactive page from report.md (or findings.md).

Markdown (CommonMark + tables), plus:
  - run ids (r008) become links that show the run's evidence on hover;
  - a line `{{figure <name> runs=r003,r008,r004 labels="k = 4,k = 8,k = 16" label="k"}}` embeds that
    figure from each listed run; with several runs it becomes a switcher over those recorded runs
    only (compare toggles, steppers), never interpolated;
  - the page ends with the runs cited, what did not work, and how to reproduce each cited run.
Figure names are the file stems in runs/<id>/figures/ (a slug of the figure's title).
"""

import html
import json
import re
import shlex
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

from ..core import compare, findings
from ..core.findings import RUN_REF
from ..core.model import Run, Verdict
from ..core.store import Campaign, LabError
from . import page
from .summary import LABELS, summarize

FIGURE_LINE = re.compile(r"^\{\{figure\s+(?P<name>[\w.-]+)(?P<attrs>[^}]*)\}\}\s*$")
ATTR = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')


def ref(run_id: str) -> str:
    return f'<a class="ref" data-run="{run_id}">{run_id}</a>'


def figure_block(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    line = state.src[state.bMarks[start] + state.tShift[start] : state.eMarks[start]]
    match = FIGURE_LINE.match(line)
    if not match:
        return False
    if not silent:
        token = state.push("lab_figure", "div", 0)
        token.meta = {"name": match["name"], "attrs": {k: a or b for k, a, b in ATTR.findall(match["attrs"])}}
        token.map = [start, start + 1]
    state.line = start + 1
    return True


def run_links(state: StateCore) -> None:
    """Turn known run ids in text into evidence links; unknown ids stay plain text."""
    known = state.env.get("runs", {})
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        children = []
        for token in block.children:
            if token.type != "text" or not RUN_REF.search(token.content):
                children.append(token)
                continue
            last = 0
            for match in RUN_REF.finditer(token.content):
                if match[0] not in known:
                    continue
                children.append(_text(token.content[last : match.start()]))
                link = Token("html_inline", "", 0)
                link.content = ref(match[0])
                children.append(link)
                last = match.end()
            children.append(_text(token.content[last:]))
        block.children = [c for c in children if c.type != "text" or c.content]


def _text(content: str) -> Token:
    token = Token("text", "", 0)
    token.content = content
    return token


def section_headings(state: StateCore) -> None:
    """The page title is the only h1: `#` and `##` become sections (h2), `###` a subsection (h3)."""
    for token in state.tokens:
        if token.type in ("heading_open", "heading_close"):
            token.tag = "h2" if token.tag in ("h1", "h2") else "h3"


def render_figure(self, tokens: list[Token], idx: int, options, env) -> str:
    return f'<div class="rfig" data-f="{tokens[idx].meta["index"]}"></div>\n'


def markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    md.block.ruler.before("paragraph", "lab_figure", figure_block)
    md.core.ruler.push("lab_run_links", run_links)
    md.core.ruler.push("lab_sections", section_headings)
    md.add_render_rule("lab_figure", render_figure)
    return md


def render(campaign: Campaign) -> str:
    config = campaign.config()
    runs = {r.id: r for r in campaign.runs()}
    source = campaign.root / "report.md"
    text = source.read_text() if source.exists() else default_report(campaign, runs)

    md = markdown()
    env = {"runs": runs}
    tokens = md.parse(text, env)
    figures = [resolve_figure(campaign, runs, t, i) for i, t in enumerate(t for t in tokens if t.type == "lab_figure")]
    body = md.renderer.render(tokens, md.options, env)

    cited = [runs[i] for i in dict.fromkeys(RUN_REF.findall(text)) if i in runs]
    shown = {r.id for r in cited} | {o["run"] for f in figures for o in f["options"]}
    data = {
        "metric": config.metric,
        "fmt": config.fmt,
        "labels": LABELS,
        "runs": {i: summarize(runs[i], runs, config) for i in shown},  # only what the page cites or plots
        "figures": figures,
    }
    meta = f"{campaign.name} · {config.metric} ({'lower' if config.goal == 'min' else 'higher'} is better) · {len(runs)} runs · {datetime.now():%d %b %Y}"
    return page.render(
        "report.html",
        data,
        title=html.escape(config.question or campaign.name),
        meta=html.escape(meta),
        body=body + appendix(campaign, cited, list(runs.values())),
    )


def resolve_figure(campaign: Campaign, runs: dict[str, Run], token: Token, index: int) -> dict:
    name, attrs = token.meta["name"], token.meta["attrs"]
    ids = [i.strip() for i in attrs.get("runs", "").split(",") if i.strip()]
    if not ids:
        raise LabError(f"figure {name} needs runs=<ids>")
    if missing := [i for i in ids if i not in runs]:
        raise LabError(f"figure {name}: no runs {missing}")
    labels = [s.strip() for s in attrs["labels"].split(",")] if "labels" in attrs else ids
    token.meta["index"] = index
    return {
        "label": attrs.get("label", ""),
        "options": [
            {"run": i, "label": labels[n] if n < len(labels) else i, "spec": figure_spec(campaign, runs[i], name)}
            for n, i in enumerate(ids)
        ],
    }


def figure_spec(campaign: Campaign, run: Run, name: str) -> dict:
    for figure in run.figures:
        if Path(figure.path).stem == name:
            return json.loads((campaign.run_dir(run.id) / figure.path).read_text())
    names = ", ".join(Path(f.path).stem for f in run.figures) or "none"
    raise LabError(f"{run.id} has no figure {name!r} (it has: {names})")


def default_report(campaign: Campaign, runs: dict[str, Run]) -> str:
    """No report.md yet: the result against the question, the next step, what we believe, then the evidence."""
    config, lines = campaign.config(), []
    kept = compare.baseline(list(runs.values()), campaign.epoch)
    if kept and (value := kept.value(config.metric)) is not None:
        result = f"**{value:.{config.fmt}f}** {config.metric} ({kept.id})"
        if (gap := compare.to_target(value, config)) is not None:
            result += f" against the target {config.target:.{config.fmt}f}: " + (
                "reached." if gap == 0 else f"{gap:.{config.fmt}f} short."
            )
        lines += ["## Result", "", result, ""]
        lines += [f"{{{{figure {Path(f.path).stem} runs={kept.id}}}}}\n" for f in kept.figures]
    for heading, key in (("Next", findings.NEXT), ("What we believe now", findings.BELIEFS)):
        if items := findings.read(campaign.findings, key):
            lines += [f"## {heading}", ""]
            lines += [f"- {f.text} ({', '.join(f.refs)})" if f.refs else f"- {f.text}" for f in items]
            lines.append("")
    return (
        "\n".join(lines)
        or "No findings yet. Write `report.md` in the campaign folder, or bullets under “What we believe now” in `findings.md`."
    )


def appendix(campaign: Campaign, cited: list[Run], runs: list[Run]) -> str:
    config = campaign.config()
    esc = html.escape

    def value(run: Run) -> str:
        v = run.value(config.metric)
        return "–" if v is None else f"{v:.{config.fmt}f}"

    parts = []
    if cited:
        rows = "".join(
            f'<tr><td>{ref(r.id)}</td><td>{esc(r.hypothesis)}</td><td class="r num">{value(r)}</td>'
            f"<td>{LABELS[str(r.verdict) if r.verdict else 'none']}</td></tr>"
            for r in cited
        )
        parts.append(
            f'<h2>Runs cited</h2><table class="lf-table"><thead><tr><th>Run</th><th>Hypothesis</th>'
            f'<th class="r">{esc(config.metric)}</th><th>Verdict</th></tr></thead><tbody>{rows}</tbody></table>'
        )
    dead = [r for r in runs if r.verdict in (Verdict.REVERT, Verdict.FAILED)]
    if dead:
        items = "".join(
            f"<li>{ref(r.id)} {esc(r.hypothesis)}"
            + (f' <span class="muted">{esc(r.verdict_note)}</span>' if r.verdict_note else "")
            + "</li>"
            for r in dead
        )
        parts.append(f"<h2>What did not work</h2><ul>{items}</ul>")
    if cited:
        blocks = "".join(
            f'<pre class="code"><code>lab -c {campaign.name} new exp repro-{r.id} --from {r.id}\n'
            f"lab -c {campaign.name} run -e repro-{r.id} -H {esc(shlex.quote('reproduce ' + r.id))} -- {esc(shlex.join(r.command))}</code></pre>"
            for r in cited
        )
        parts.append(
            f'<h2>Reproduce</h2><p class="muted">From the lab, each cited run\'s exact code is in its snapshot:</p>{blocks}'
        )
    return "\n".join(parts)
