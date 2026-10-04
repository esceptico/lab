"""Launch a Prime Intellect Hosted Training run and record it as a lab run.

    lab run -H "..." -P "..." -- python run.py rl.toml --metric reward

Launches with `prime train <config>`, polls until the run is COMPLETED, FAILED or STOPPED,
then logs every numeric field of every metric record (by step), the final value of
`--metric` as the summary, and the run's real cost from `prime train usage`.
Ctrl-C detaches: the hosted run keeps going; stop it with `prime train stop <id>`.
"""

import argparse
import json
import subprocess
import sys
import time

from lab import artifact, cost, log, summary

TERMINAL = {"COMPLETED", "FAILED", "STOPPED"}


def prime(*args: str, flag: bool = True) -> dict:
    # `train`, `get` and `usage` take `-o json`; `metrics` and `progress` always print JSON.
    out = subprocess.run(
        ["prime", *args, *(["-o", "json"] if flag else [])], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def run_of(payload: dict) -> dict:
    return payload.get("run", payload)


def pick(record: dict, name: str) -> float | None:
    """The metric by exact key, else among keys that contain it the mean (Prime's records hold
    `.../reward/mean`, `/max`, `/min`, `/std` for each environment), else the shortest such key."""
    if isinstance(record.get(name), (int, float)):
        return record[name]
    found = sorted((k for k, v in record.items() if name in k and isinstance(v, (int, float))), key=len)
    means = [k for k in found if k.endswith("mean")]
    return record[(means or found)[0]] if found else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("config")
    p.add_argument("--metric", default="reward", help="metric key (or substring) to report as the summary")
    p.add_argument("--poll", type=float, default=30.0, help="seconds between status checks")
    p.add_argument("--env-file", help="passed through to prime train")
    args = p.parse_args()

    launch = ["train", args.config, "-y"] + (["--env-file", args.env_file] if args.env_file else [])
    run = run_of(prime(*launch))
    run_id = run.get("runId") or run["id"]  # launch prints {"run": {"runId"}}; get prints {"run": {"id", ...}}
    print(f"prime run {run_id} launched ({run.get('status', '?')})", flush=True)

    status = run.get("status", "PENDING")
    try:
        while status not in TERMINAL:
            time.sleep(args.poll)
            status = run_of(prime("train", "get", run_id)).get("status", status)
            progress = prime("train", "progress", run_id, flag=False)
            print(f"{time.strftime('%H:%M:%S')} {status} step {progress.get('latest_step')}", flush=True)
    except (KeyboardInterrupt, subprocess.CalledProcessError) as error:
        # Detached by hand, or the CLI failed mid-poll: the hosted run keeps billing, so record what it cost so far.
        cost(
            prime("train", "usage", run_id)["total_cost_usd"],
            f"prime run {run_id}, spent before lab stopped following it",
        )
        why = "detached" if isinstance(error, KeyboardInterrupt) else f"prime failed ({error.stderr.strip()})"
        print(f"\n{why}; the run continues on Prime. Stop it with: prime train stop {run_id}", flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1

    records = prime("train", "metrics", run_id, flag=False).get("metrics", [])
    last = None
    for record in records:
        values = {k: v for k, v in record.items() if isinstance(v, (int, float)) and k != "step"}
        log(step=record.get("step"), **values)
        value = pick(record, args.metric)
        last = value if value is not None else last
    if last is not None:
        summary(**{args.metric: last})

    usage = prime("train", "usage", run_id)
    cost(usage["total_cost_usd"], f"prime run {run_id}")

    with open("prime_run.json", "w") as f:
        json.dump({"run": run_of(prime("train", "get", run_id)), "usage": usage}, f, indent=2)
    artifact("prime_run.json", f"Prime run {run_id}")

    print(f"prime run {run_id} {status}", flush=True)
    return 0 if status == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
