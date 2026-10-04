"""Copying and fingerprinting code trees. One ignore rule for everything that copies or hashes code."""

import hashlib
import os
import shutil
from pathlib import Path

# Hidden entries (.git, .env, .DS_Store, .venv, …) are always skipped; so are these.
SKIP_DIRS = frozenset({"__pycache__", "node_modules", "wandb", "checkpoints", "outputs"})
MAX_FILE = 1 << 20
MAX_TOTAL = 20 << 20


def ignored(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIRS


def files(root: Path, follow: bool = False) -> list[Path]:
    """Files under root that are not ignored, in a stable order; ignored folders are never walked, and links
    that point nowhere are left out. `follow` walks into linked folders (eval data linked into locked/)."""
    found = []
    for directory, dirs, names in os.walk(root, followlinks=follow):
        dirs[:] = sorted(d for d in dirs if not ignored(d))
        found += [p for n in sorted(names) if not ignored(n) and (p := Path(directory, n)).exists()]
    return found


def linked_folders(root: Path) -> list[Path]:
    """Folders under root that are links: copies keep them as links instead of copying what they point to."""
    found = []
    for directory, dirs, _ in os.walk(root):
        dirs[:] = [d for d in dirs if not ignored(d)]
        found += [Path(directory, d) for d in dirs if Path(directory, d).is_symlink()]
    return found


def copy_tree(source: Path, target: Path) -> list[str]:
    """The record's copy: within size limits. Returns what was left out."""
    skipped, total = [f"{p.relative_to(source)}/ (a linked folder)" for p in linked_folders(source)], 0
    for path in files(source):
        size, rel = path.stat().st_size, path.relative_to(source)
        if size > MAX_FILE or total + size > MAX_TOTAL:
            skipped.append(str(rel))
            continue
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / rel)
        total += size
    return skipped


def copy_code(source: Path, target: Path) -> None:
    """Everything that is not ignored, with no size limit (the folder a run executes in, a branched experiment).
    Links stay links: a linked dataset is not copied into every run."""
    shutil.copytree(source, target, symlinks=True, ignore=lambda _, names: [n for n in names if ignored(n)])


def hash_tree(root: Path) -> str:
    """Content hash over relative paths and bytes, streamed, so large eval data does not load into memory."""
    digest = hashlib.sha256()
    if root.exists():
        for path in files(root, follow=True):  # eval data is often a linked folder: its contents count
            name = str(path.relative_to(root)).encode()
            digest.update(len(name).to_bytes(4, "big") + name)
            with open(path, "rb") as f:
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
    return digest.hexdigest()[:16]
