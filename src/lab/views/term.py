"""How text output looks. On a terminal: colour for meaning and columns fitted to the width. Piped (an agent, a
file, `grep`): the same words with no escape codes, and tables as tab-separated rows with nothing cut off.

NO_COLOR turns colour off; CLICOLOR_FORCE or FORCE_COLOR turns it on when piped (https://no-color.org).
"""

import contextlib
import os
import re
import shutil
import sys
import textwrap
from collections.abc import Iterator

ANSI = re.compile(r"\x1b\[[0-9;]*m")
CODES = {"good": "32", "bad": "31", "dim": "90", "bold": "1"}
FORCED: dict[str, object] = {}  # set by layout(), for text rendered somewhere other than stdout


@contextlib.contextmanager
def layout(terminal: bool, colour: bool, width: int) -> Iterator[None]:
    """Render as if to a terminal of this kind, e.g. `lab ls` as the board shows it."""
    FORCED.update(terminal=terminal, colour=colour, width=width)
    try:
        yield
    finally:
        FORCED.clear()


def terminal() -> bool:
    """Lay out for a person: aligned columns fitted to the width, wrapped prose."""
    return bool(FORCED["terminal"]) if FORCED else sys.stdout.isatty()


def colour() -> bool:
    if FORCED:
        return bool(FORCED["colour"])
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE", "0") != "0" or os.environ.get("FORCE_COLOR"):
        return True
    return terminal() and os.environ.get("TERM") != "dumb"


def width() -> int:
    return int(FORCED["width"]) if FORCED else shutil.get_terminal_size((120, 24)).columns


def paint(text: str, *roles: str) -> str:
    roles = tuple(r for r in roles if r)
    if not text or not roles or not colour():
        return text
    return f"\x1b[{';'.join(CODES[r] for r in roles)}m{text}\x1b[0m"


def visible(text: str) -> int:
    return len(ANSI.sub("", text))


def cut(text: str, room: int) -> str:
    """One line of plain text within `room` columns, ending in … when it had to be cut."""
    text = " ".join(text.split())
    return text if len(text) <= room else text[: max(room - 1, 0)].rstrip() + "…"


def wrap(text: str, indent: int = 0) -> str:
    """Prose wrapped to the terminal on a terminal; one line when piped, so a reader can grep it."""
    text = " ".join(text.split())
    if not terminal() or ANSI.search(text):  # coloured text is short; wrapping would count its escape codes
        return text
    lines = textwrap.wrap(text, max(width() - indent, 40), break_on_hyphens=False, break_long_words=False) or [""]
    return ("\n" + " " * indent).join(lines)


def table(head: list[str], rows: list[list[str]], right: frozenset[int] = frozenset(), flex: int | None = None) -> str:
    """Rows under a header. On a terminal: aligned, with column `flex` cut to fit the width. Piped: tab-separated.

    Cells may carry colour; a row of one cell is a divider line that spans the table.
    """
    if not terminal():  # a tab or newline inside a cell would split its row
        return "\n".join(
            "\t".join(" ".join(ANSI.sub("", c).split()) for c in row) for row in [head, *rows] if len(row) > 1
        )
    cols = range(len(head))
    full = [r for r in rows if len(r) > 1]
    widths = [max(visible(r[i]) for r in [head, *full]) for i in cols]
    if flex is not None:
        others = sum(w for i, w in enumerate(widths) if i != flex) + 2 * (len(widths) - 1)
        widths[flex] = max(min(widths[flex], width() - others), 12)
        for r in full:
            r[flex] = cut(ANSI.sub("", r[flex]), widths[flex])

    def line(row: list[str], style: str = "") -> str:
        cells = []
        for i, cell in zip(cols, row, strict=True):
            pad = " " * (widths[i] - visible(cell))
            cells.append(pad + cell if i in right else cell + pad)
        return paint("  ".join(cells).rstrip(), style)

    total = sum(widths) + 2 * (len(widths) - 1)
    out = [line(head, "dim")]
    for row in rows:
        out.append(paint(divider(row[0], total), "dim") if len(row) == 1 else line(row))
    return "\n".join(out)


def divider(label: str, total: int) -> str:
    side = max((total - len(label) - 2) // 2, 2)
    return f"{'─' * side} {label} {'─' * side}"


def pairs(items: list[tuple[str, str]], indent: int = 0) -> str:
    """Label-value lines with the values aligned; a value wraps under itself on a terminal."""
    key = max((len(k) for k, _ in items), default=0) + 2
    return "\n".join(" " * indent + paint(k.ljust(key), "dim") + wrap(v, indent + key) for k, v in items)
