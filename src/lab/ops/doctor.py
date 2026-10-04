"""`lab doctor`: which tools, keys and logins are ready."""

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..core.store import Lab, LabError

MIN_FREE_GB = 20
RESEARCH_SKILLS = ("ml-research", "ml-compute", "mech-interp")
USER_SKILL_DIRS = (".claude/skills", ".agents/skills")
MARKS = {True: "ok  ", False: "fix ", None: "--  "}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None: optional and not set up
    detail: str
    fix: str = ""


def command_output(command: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return out.returncode, (out.stdout + out.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)


def lab_home() -> Check:
    try:
        return Check("lab home", True, str(Lab.find().root))
    except LabError:
        return Check("lab home", False, "not inside a lab", "lab init <dir>, or cd into one, or set LAB_HOME")


def skills() -> Check:
    """The lab skill is in this workspace (needed); the research skills are installed for the user (optional)."""
    missing = [
        name
        for name in RESEARCH_SKILLS
        if not any((Path.home() / d / name / "SKILL.md").exists() for d in USER_SKILL_DIRS)
    ]
    try:
        skill_missing = not (Lab.find().root / ".claude" / "skills" / "lab" / "SKILL.md").exists()
    except LabError:
        skill_missing = False
    detail = ("lab skill missing in this lab · " if skill_missing else "") + (
        f"optional, not installed: {', '.join(missing)}" if missing else "research skills installed"
    )
    fixes = (["lab sync"] if skill_missing else []) + (["npx skills add esceptico/skills"] if missing else [])
    return Check("skills", False if skill_missing else None if missing else True, detail, " ; ".join(fixes))


def python() -> Check:
    return Check("python", True, f"{platform.python_version()} · {platform.system()} {platform.machine()}")


def installed(name: str, fix: str) -> Check:
    path = shutil.which(name)
    return Check(name, bool(path), path or "not found", fix)


def tinker() -> Check:
    ready = bool(os.environ.get("TINKER_API_KEY"))
    return Check(
        "tinker",
        ready or None,
        "TINKER_API_KEY set" if ready else "TINKER_API_KEY not set",
        "create a key in the Tinker console, export TINKER_API_KEY",
    )


def prime() -> Check:
    if not shutil.which("prime"):
        return Check("prime", None, "not installed", "uv tool install prime")
    _, text = command_output(["prime", "--version"])
    version = re.search(r"version:\s*([\d.]+)", text)
    newer = re.search(r"available:\s*([\d.]+)", text)
    logged_in = command_output(["prime", "whoami"])[0] == 0
    detail = (
        f"CLI {version[1] if version else '?'}"
        + (f", {newer[1]} available" if newer else "")
        + (" · logged in" if logged_in else " · not logged in")
    )
    fixes = (["prime upgrade"] if newer else []) + ([] if logged_in else ["prime login"])
    return Check("prime", logged_in and not newer, detail, " ; ".join(fixes))


def modal() -> Check:
    installed = bool(shutil.which("modal"))
    token = Path.home().joinpath(".modal.toml").exists() or bool(os.environ.get("MODAL_TOKEN_ID"))
    fixes = ([] if installed else ["uv tool install modal"]) + ([] if token else ["modal token new"])
    detail = ("installed" if installed else "not installed") + (" · token found" if token else " · no token")
    return Check("modal", (installed and token) if installed else None, detail, " ; ".join(fixes))


def runpod() -> Check:
    installed = bool(shutil.which("runpodctl"))
    key = bool(os.environ.get("RUNPOD_API_KEY")) or Path.home().joinpath(".runpod", "config.toml").exists()
    detail = ("runpodctl installed" if installed else "runpodctl not installed") + (
        " · key found" if key else " · no key"
    )
    return Check(
        "runpod",
        key if installed else None,
        detail,
        "brew install runpod/runpodctl/runpodctl ; runpodctl config --apiKey …",
    )


def hugging_face() -> Check:
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    token = bool(os.environ.get("HF_TOKEN")) or Path(os.environ.get("HF_TOKEN_PATH", home / "token")).exists()
    cache = home / "hub"
    code, du = command_output(["du", "-sk", str(cache)], timeout=30) if cache.exists() else (1, "")
    size = f"{int(du.split()[0]) / 1e6:.1f} GB cached" if code == 0 and du else "no cache"
    return Check(
        "hugging face",
        token,
        ("token found" if token else "no token (gated repos will fail)") + f" · {size}",
        "hf auth login",
    )


def disk() -> Check:
    free = shutil.disk_usage(Path.home()).free / 1e9
    return Check("disk", free > MIN_FREE_GB, f"{free:.0f} GB free", "free space before pulling models")


def checks() -> list[Check]:
    return [
        lab_home(), skills(), python(), installed("uv", "brew install uv"), installed("git", "xcode-select --install"),
        tinker(), prime(), modal(), runpod(), hugging_face(), disk(),
    ]  # fmt: skip
