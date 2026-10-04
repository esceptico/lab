"""Download a Hugging Face model or dataset at a pinned revision and report what was pinned.

Run by `lab fetch` through `uv run --with huggingface_hub python -m lab.hf_fetch`.
Prints one JSON line: repo, kind, requested and resolved revision (commit sha), license, size, path.
"""

import argparse
import fnmatch
import json

from huggingface_hub import HfApi, snapshot_download


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["model", "dataset"])
    p.add_argument("repo", help="org/name, optionally @revision")
    p.add_argument("--include", action="append", help="glob of files to fetch (repeatable)")
    args = p.parse_args()
    repo, _, revision = args.repo.partition("@")
    api = HfApi()
    info = (
        api.model_info(repo, revision=revision or None, files_metadata=True)
        if args.kind == "model"
        else api.dataset_info(repo, revision=revision or None, files_metadata=True)
    )
    card = info.card_data.to_dict() if info.card_data else {}
    license = card.get("license")
    fetched = [
        s for s in info.siblings or [] if not args.include or any(fnmatch.fnmatch(s.rfilename, g) for g in args.include)
    ]  # the files --include let through, as snapshot_download matches them
    path = snapshot_download(repo, repo_type=args.kind, revision=info.sha, allow_patterns=args.include)
    print(
        json.dumps(
            {
                "repo": repo,
                "kind": args.kind,
                "requested": revision or "main",
                "revision": info.sha,
                "license": ", ".join(license) if isinstance(license, list) else license,  # dataset cards list several
                "gated": getattr(info, "gated", None) or False,
                "include": args.include or [],
                "bytes": sum(s.size or 0 for s in fetched),
                "path": path,
            }
        )
    )


if __name__ == "__main__":
    main()
