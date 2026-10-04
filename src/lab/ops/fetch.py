"""`lab fetch`: a Hugging Face model or dataset at a pinned commit, recorded in pins.json."""

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel

from ..core.model import now
from ..core.store import LabError

PINS_FILE = "pins.json"


class Pin(BaseModel):
    """What lab.hf_fetch reports: the commit actually downloaded, and what it is."""

    repo: str
    kind: str
    requested: str
    revision: str
    license: str | None = None
    gated: bool | str = False
    include: list[str] = []
    bytes: int = 0
    path: str


def fetch(kind: str, repo: str, include: list[str], pins_dir: Path) -> Pin:
    # huggingface_hub runs in its own ephemeral environment, not in lab's; hf_fetch imports nothing from lab.
    script = str(Path(__file__).parents[1] / "hf_fetch.py")
    command = ["uv", "run", "--no-project", "--with", "huggingface_hub", "python", script, kind, repo]
    for pattern in include:
        command += ["--include", pattern]
    out = subprocess.run(command, capture_output=True, text=True)
    if out.returncode != 0:  # the exception's last line says why (gated, no such revision); the rest is a traceback
        reason = next((line for line in reversed(out.stderr.strip().splitlines()) if line.strip()), "no output")
        raise LabError(f"fetch failed for {repo}: {reason.strip()}")
    pin = Pin.model_validate_json(out.stdout.strip().splitlines()[-1])
    record(pin, pins_dir / PINS_FILE)
    return pin


def record(pin: Pin, path: Path) -> None:
    pins = json.loads(path.read_text()) if path.exists() else {}
    pins[f"{pin.kind}:{pin.repo}"] = pin.model_dump(
        include={"requested", "revision", "include", "license", "gated", "bytes"}
    ) | {"fetched": now().isoformat()}
    path.write_text(json.dumps(pins, indent=2) + "\n")
