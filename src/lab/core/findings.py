"""Reading findings.md: the bullets under a heading ("What we believe now", "Next"), each with the run ids it cites."""

import re
from dataclasses import dataclass
from pathlib import Path

RUN_REF = re.compile(r"\br\d{3,}\b")
# "(r002 vs r001)" is shown as links next to the text, so the parenthetical is dropped from it.
REF_GROUP = re.compile(r"\s*\((?:\s*(?:r\d{3,}|vs\.?|and|,|·)\s*)+\)")
BELIEFS, NEXT = "what we believe", "next"


@dataclass(frozen=True)
class Finding:
    text: str
    refs: tuple[str, ...]


def read(path: Path, heading: str = BELIEFS) -> list[Finding]:
    if not path.exists():
        return []
    found, inside = [], False
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith(heading)
        elif inside and line.lstrip().startswith(("- ", "* ")):
            text = line.lstrip()[2:].strip()
            found.append(Finding(REF_GROUP.sub("", text), tuple(dict.fromkeys(RUN_REF.findall(text)))))
    return found
