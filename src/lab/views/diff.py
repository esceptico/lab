"""What changed between two runs: command and code (experiment snapshot and lib/)."""

import difflib
import shlex
from dataclasses import dataclass
from pathlib import Path

from ..core.model import Run
from ..core.store import Campaign

MAX_LINES = 120
CONTEXT = 1


@dataclass(frozen=True)
class Changes:
    command: tuple[str, str] | None  # (before, after) when it changed
    diff: str | None  # unified-style lines: "@@ file", "+", "-", "  …" between hunks


def between(campaign: Campaign, parent: Run | None, run: Run) -> Changes:
    if parent is None:
        return Changes(None, None)
    command = (shlex.join(parent.command), shlex.join(run.command)) if parent.command != run.command else None
    old, new = campaign.run_dir(parent.id), campaign.run_dir(run.id)
    parts = [code_diff(old / "code", new / "code"), code_diff(old / "lib", new / "lib", prefix="lib/")]
    return Changes(command, "\n".join(p for p in parts if p) or None)


def code_diff(old: Path, new: Path, prefix: str = "") -> str | None:
    files = sorted({p.relative_to(old) for p in _files(old)} | {p.relative_to(new) for p in _files(new)})
    lines: list[str] = []
    for rel in files:
        a, b = _lines(old / rel), _lines(new / rel)
        if a == b:
            continue
        hunks = [
            line for line in difflib.unified_diff(a, b, lineterm="", n=CONTEXT) if not line.startswith(("---", "+++"))
        ]
        lines.append(f"@@ {prefix}{rel}")
        lines += ["  …" if line.startswith("@@") else line for line in hunks[1:] if line]
    if len(lines) > MAX_LINES:
        lines = [*lines[:MAX_LINES], f"  … {len(lines) - MAX_LINES} more lines"]
    return "\n".join(lines) or None


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text().splitlines()
    except UnicodeDecodeError:
        return ["(binary file)"]
