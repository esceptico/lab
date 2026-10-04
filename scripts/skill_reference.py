"""Generate the `lab` skill's reference files from the code, so they cannot drift from it.

    uv run python scripts/skill_reference.py

Writes cli.md (every command's --help), figures.md (lab.fig signatures, docstrings, examples)
and running.md (logging helpers, remote runners, reports, templates). Re-run after changing
the CLI, lab.fig, or a runner.
"""

import argparse
import contextlib
import inspect
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import lab  # noqa: E402
from lab import cli, fig, interp  # noqa: E402
from lab.core.campaigns import BUILTIN_TEMPLATES  # noqa: E402

EXAMPLES = {
    "line": 'fig.line({"trained": S, "random-init": S0}, log_y=True, mark_x=(8.5, "top 8 ablated"),\n         x_label="singular index", title="Trained Jacobians concentrate", caption="...")',
    "heatmap": 'fig.heatmap(effect, x=tokens, y=[f"L{i}" for i in range(n_layers)], diverging=True,\n            value_label="recovered", annotate=(13, 6, "L13 · bomb"), title="Patching")',
    "tokens": 'fig.tokens([("harmful", toks_a, proj_a), ("harmless", toks_b, proj_b)], value_label="projection",\n           title="What the top direction reads")',
    "dots": 'fig.dots([("Random dirs", 0.03, 0.01, 0.05), {"label": "Jacobian k=8", "mean": 0.47, "lo": 0.44, "hi": 0.50, "highlight": True}],\n         reference=(0.03, "random", 0.02), x_label="refusal drop", title="Bases vs control")',
    "scatter": 'fig.scatter({"harmful": pts_a, "harmless": pts_b}, x_label="PC 1", y_label="PC 2", title="Layer 20 PCA")',
    "hist": 'fig.hist({"harmful": proj_a, "harmless": proj_b}, x_label="projection", bins=40, title="Separation")',
    "bars": 'fig.bars(["GPQA", "MMLU-Pro"], {"zero-shot": [41.2, 62.0], "tuned": [49.1, 69.8]}, title="Accuracy (%)")',
    "reliability": 'fig.reliability({"zero-shot": (conf0, correct0), "tuned": (conf1, correct1)}, title="Calibration")',
    "multiples": 'fig.multiples({"layers 10→16": {"J": y1, "random": r1}, "layers 14→24": {"J": y2, "random": r2}},\n              x=[1, 2, 4, 8, 16, 32], log_x=True, muted=["random"], highlight="layers 14→24", title="Drop vs k")',
    "table": 'fig.table(rows, columns=[{"key": "label", "label": "Basis"},\n    {"key": "mean", "label": "Drop", "kind": "bar", "lo": "lo", "hi": "hi"},\n    {"key": "run", "label": "Run", "kind": "run"}], reference=0.03, title="Results")',
}


def help_text(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.build_parser().parse_args([*argv, "--help"])
    return out.getvalue().strip()


def commands() -> list[list[str]]:
    parser = cli.build_parser()
    found = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                nested = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
                if nested:
                    found += [[name, n] for n in nested[0].choices]
                else:
                    found.append([name])
    return found


def header(title: str) -> str:
    return f"# {title}\n\nGenerated from the code by `scripts/skill_reference.py`; if this disagrees with `lab <cmd> --help`, the CLI wins.\n\n"


def cli_md() -> str:
    parts = [header("lab CLI reference"), "```\n" + help_text([]) + "\n```\n"]
    for argv in commands():
        parts.append(f"## lab {' '.join(argv)}\n\n```\n{help_text(argv)}\n```\n")
    return "\n".join(parts)


def figures_md() -> str:
    parts = [header("lab.fig reference"), inspect.getdoc(fig) + "\n"]
    for name in fig.__all__:
        fn = getattr(fig, name)
        doc = inspect.getdoc(fn) or ""
        parts.append(
            f"## fig.{name}\n\n```python\nfig.{name}{signature(fn)}\n```\n\n{doc}\n\n```python\n{EXAMPLES[name]}\n```\n"
        )
    return "\n".join(parts)


def signature(fn) -> str:
    """The signature as source would read it: callables as their names, not their reprs."""
    return (
        re.sub(r"<(?:built-in )?(?:method|function) (\w+)[^>]*>", r"\1", str(inspect.signature(fn)))
        .replace("NoneType", "None")
        .replace("typing.", "")
        .replace("collections.abc.", "")
    )


def interp_md() -> str:
    parts = ["## Interpretability helpers: lab.interp\n\n", inspect.getdoc(interp), "\n"]
    for name, fn in inspect.getmembers(interp, inspect.isfunction):
        if fn.__module__ == interp.__name__ and not name.startswith("_"):
            parts.append(
                f"\n### interp.{name}\n\n```python\ninterp.{name}{signature(fn)}\n```\n\n{inspect.getdoc(fn) or ''}\n"
            )
    return "".join(parts)


def module_doc(path: Path) -> str:
    source = path.read_text()
    return inspect.cleandoc(source.split('"""')[1])


def running() -> str:
    src = ROOT / "src" / "lab"
    templates = []
    for readme in sorted(BUILTIN_TEMPLATES.glob("*/README.md")):
        summary = next(p for p in readme.read_text().split("\n\n") if p.strip() and not p.startswith("#"))
        templates.append(f"- `{readme.parent.name}`: {' '.join(summary.split())}")
    ssh_help = subprocess.run(
        [sys.executable, "-m", "lab.ssh_app", "--help"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(src.parent), "PATH": "/usr/bin:/bin"},
    ).stdout.strip()
    return "".join(
        [
            header("Running, logging, remote machines, reports"),
            "## Logging from inside a run\n\n",
            inspect.getdoc(lab),
            "\n\n",
            "Environment set by `lab run`: `LAB_RUN_DIR`, `LAB_RUN_ID`, `LAB_CAMPAIGN_DIR`, `LAB_LOCKED_DIR`, `LAB_HOME`; ",
            "`PYTHONPATH` gets the `lab` package (alone, without lab's own dependencies) and `lib/`, so any interpreter or venv ",
            "can `from lab import ...` and import `lib/` modules. On a remote machine (`lab.ssh_app`, `lab.modal_app`) the ",
            "script gets `LAB_RUN_DIR`, `LAB_RUN_ID` and `LAB_LOCKED_DIR`, with the package and `lib/` on `PYTHONPATH`.\n\n",
            "## Templates\n\n",
            "\n".join(templates),
            "\n\nStart one with `lab new exp <name> --template <template>`; each folder has a README with the exact command.\n\n",
            "## Modal: lab.modal_app\n\n",
            module_doc(src / "modal_app.py"),
            "\n\n",
            "Options of the local entrypoint: `--script` (default train.py), `--args` (quoted), `--gpu` (T4, L4, A10, L40S, A100-40GB, A100-80GB, H100, H200, B200; `:N` for several), `--timeout-hours` (default 6).\n\n",
            "## Any SSH machine: lab.ssh_app\n\n",
            module_doc(src / "ssh_app.py"),
            "\n\n```\n",
            ssh_help,
            "\n```\n\n",
            "## Remote outputs: lab.remote\n\n",
            module_doc(src / "remote.py"),
            "\n\n",
            "## Benchmarks: lab bench\n\n",
            module_doc(src / "bench_run.py"),
            "\n\n",
            "## Reports: lab report\n\n",
            module_doc(src / "views" / "report.py"),
            "\n\n",
            interp_md(),
        ]
    )


def main() -> None:
    out = ROOT / "src" / "lab" / "skill" / "references"
    (out / "cli.md").write_text(cli_md())
    (out / "figures.md").write_text(figures_md())
    (out / "running.md").write_text(running())
    for name in ("cli.md", "figures.md", "running.md"):
        print(out / name, len((out / name).read_text().splitlines()), "lines")


if __name__ == "__main__":
    main()
