"""What the SSH and Modal runners share: the folders they ship, and moving a run's outputs back.

Remote code logs into its own scratch run directory (LAB_RUN_DIR there); when it finishes,
`pack` collects what `lab` records and `unpack` merges it into the real run directory here.
"""

import os
import secrets
import sys
from pathlib import Path

KEEP = ("metrics.jsonl", "figures", "artifacts")
MAX_FILE = 50 << 20
SECRETS = ("HF_TOKEN", "WANDB_API_KEY")  # gated models need the first


def scratch_name(run_id: str) -> str:
    """Run ids repeat across campaigns and labs: a folder of its own keeps another run's files out of this one."""
    return f"{Path(os.environ.get('LAB_CAMPAIGN_DIR', 'lab')).name}-{run_id}-{secrets.token_hex(3)}"


def shipped() -> list[tuple[Path, str]]:
    """The campaign's locked/ and the lab's lib/ that exist, with their folder names on the machine."""
    home = os.environ.get("LAB_HOME")
    sources = [(os.environ.get("LAB_LOCKED_DIR"), "locked"), (home and f"{home}/lib", "lib")]
    return [(Path(source), name) for source, name in sources if source and Path(source).is_dir()]


def pack(run_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in KEEP:
        path = run_dir / name
        items = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for item in items:
            rel = str(item.relative_to(run_dir))
            if item.stat().st_size > MAX_FILE:  # a checkpoint passed as an artifact
                print(f"lab: not copied back, over {MAX_FILE >> 20} MB: {rel}", file=sys.stderr)
            else:
                files[rel] = item.read_bytes()
    return files


def unpack(files: dict[str, bytes], run_dir: Path) -> None:
    for rel, data in files.items():
        target = run_dir / rel
        if not target.resolve().is_relative_to(run_dir.resolve()):
            raise ValueError(f"refusing to write outside the run: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "ab" if rel == "metrics.jsonl" else "wb") as f:  # local cost lines stay
            f.write(data)
