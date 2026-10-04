"""Assembling a self-contained HTML page from a shell in web/, its assets, the data and text slots."""

import json
import re
from pathlib import Path

from .. import events

WEB = Path(__file__).parent / "web"
SLOT = re.compile(r"<!-- lab:([\w.-]+) -->")


def render(shell: str, data: object, **slots: str) -> str:
    """One pass over the shell's <!-- lab:NAME --> markers: a file name inlines that asset, `data` is the
    page's JSON, anything else comes from `slots`. Inserted text is never scanned again."""
    payload = json.dumps(events.plain(data), separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    values = {**slots, "data": payload}
    return SLOT.sub(lambda m: values[m[1]] if m[1] in values else (WEB / m[1]).read_text(), (WEB / shell).read_text())
