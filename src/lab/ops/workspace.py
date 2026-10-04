"""`lab init` and `lab sync`: a lab workspace, with guidance and the lab skill for coding agents."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..core.store import MARKER, OLD_MARKER, LabError

SKILL = Path(__file__).resolve().parent.parent / "skill"
SKILL_DIRS = (".claude/skills/lab", ".agents/skills/lab")  # where Claude Code and other agents look
MANAGED = "<!-- managed by lab: `lab sync` rewrites this file; delete this line to keep your edits -->"

AGENTS_MD = f"""{MANAGED}
# Lab workspace

Research here is run through the `lab` CLI: every run is recorded, and comparisons stay honest.

- Before proposing work: `lab doctor`, then inside a campaign `lab status` (the result, Next, the last runs),
  `lab ls` and `findings.md`. Add `--json` to a read command when you parse its output.
- Run every experiment as `lab run -H "hypothesis" -P "prediction" -- <command>` (add `-d` for anything
  long, so it outlives the session), and judge it with `lab verdict <run> keep|revert|inconclusive|failed -m "why"`
  before starting the next.
- Show results with `lab board --open`; figures come from the runs themselves (`lab.log`, `lab.fig`).
  Report the latest result against the question first, then the next step; history only when asked.
- Hypotheses, predictions, verdict notes and findings are read by people on the board: write plain
  sentences with spaces between words and numbers ("208 of 256 correct (81.3%)", not "208/256=81.25%dev").
- The `lab` skill has the commands and rules. For research method, compute and interpretability,
  use the `ml-research`, `ml-compute` and `mech-interp` skills when they are installed.
"""

CLAUDE_MD = f"""{MANAGED}
@AGENTS.md
"""

GITIGNORE = """\
# lab: copies and outputs that are large or regenerated
campaigns/*/runs/*/work/
campaigns/*/runs/*/lm_eval/
board/
reports/
smoke-failures/
"""


@dataclass
class Changes:
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # user-edited files that sync left alone


def init(root: Path) -> Changes:
    if (root / MARKER).exists() or (root / OLD_MARKER).exists():
        raise LabError(f"{root} is already a lab; `lab sync` refreshes its guidance and skill")
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("# Marks the root of a lab: `lab` walks up from the current directory to find it.\n")
    for folder in ("campaigns", "lib"):
        (root / folder).mkdir(exist_ok=True)
    changes = Changes(written=[MARKER, "campaigns/", "lib/"])
    gitignore = root / ".gitignore"
    if "# lab:" not in (gitignore.read_text() if gitignore.exists() else ""):
        with open(gitignore, "a") as f:
            f.write(GITIGNORE)
        changes.written.append(".gitignore")
    return sync(root, changes)


def sync(root: Path, changes: Changes | None = None) -> Changes:
    """Write the managed guidance files and the lab skill; files whose marker was removed are kept."""
    changes = changes or Changes()
    if (root / OLD_MARKER).exists() and not (root / MARKER).exists():
        (root / OLD_MARKER).rename(root / MARKER)
        changes.written.append(f"{MARKER} (was {OLD_MARKER})")
    for name, text in (("AGENTS.md", AGENTS_MD), ("CLAUDE.md", CLAUDE_MD)):
        path = root / name
        if path.exists() and MANAGED not in path.read_text():
            changes.kept.append(name)
            continue
        path.write_text(text)
        changes.written.append(name)
    for folder in SKILL_DIRS:
        target = root / folder
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__"))
        changes.written.append(f"{folder}/")
    return changes
