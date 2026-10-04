"""Run any experiment script on a Modal GPU and bring its lab outputs home.

    lab run -H "..." -- modal run -m lab.modal_app --script train.py --args "--lr 3e-4" --gpu A10

The experiment folder, the campaign's locked/ folder and the lab's lib/ are shipped into the
container; `requirements.txt` in the experiment folder is installed into the image (cached).
Inside, the script logs with `lab.log` / `lab.fig` as usual into a folder on the `lab-data` volume,
so what it logged survives the container: when it ends, or dies (timeout, out of memory, preemption),
metrics, figures and artifacts are copied into the local run. Checkpoints belong in $LAB_DATA_DIR
(the same volume), not in artifacts. Cost is not logged: Modal bills your account, and lab records only
amounts a service reports.

Needs `pip install modal` and `modal token new` once.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import modal

from lab import run_dir
from lab.core.snapshot import ignored
from lab.remote import SECRETS, pack, scratch_name, shipped, unpack

EXP, DATA = "/root/exp", "/data"
RUNS = f"{DATA}/lab-runs"


def skip(path) -> bool:
    return any(ignored(part) for part in Path(path).parts)  # the rule snapshots use


image = modal.Image.debian_slim(python_version="3.12").pip_install("numpy")
if modal.is_local():
    here = Path.cwd()
    requirements = here / "requirements.txt"
    if requirements.exists():
        image = image.pip_install_from_requirements(str(requirements))
    image = image.add_local_python_source("lab")
    image = image.add_local_dir(here, EXP, ignore=skip)
    for source, name in shipped():
        image = image.add_local_dir(source, f"/root/{name}", ignore=skip)

app = modal.App("lab", image=image)
volume = modal.Volume.from_name("lab-data", create_if_missing=True)


@app.function(timeout=6 * 60 * 60, volumes={DATA: volume})
def execute(script: str, args: str, run_id: str, folder: str) -> dict:
    scratch = Path(RUNS) / folder
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        LAB_RUN_DIR=str(scratch),
        LAB_RUN_ID=run_id,
        LAB_LOCKED_DIR="/root/locked",
        LAB_DATA_DIR=DATA,
        PYTHONUNBUFFERED="1",
        PYTHONPATH=os.pathsep.join(["/root/lib", os.environ.get("PYTHONPATH", "")]),
    )
    code = subprocess.call([sys.executable, script, *shlex.split(args)], cwd=EXP, env=env)
    return {"code": code, "files": take(scratch)}


@app.function(volumes={DATA: volume})
def collect(folder: str) -> dict:
    """What a run logged before its container died: the volume keeps what was committed."""
    volume.reload()
    return take(Path(RUNS) / folder)


def take(scratch: Path) -> dict:
    files = pack(scratch) if scratch.is_dir() else {}
    shutil.rmtree(scratch, ignore_errors=True)  # home now: the volume keeps checkpoints, not run logs
    volume.commit()
    return files


@app.local_entrypoint()
def main(script: str = "train.py", args: str = "", gpu: str = "A10", timeout_hours: float = 6.0):
    here = run_dir()
    run_id = here.name if here else "manual"
    folder = scratch_name(run_id)
    env = {k: os.environ[k] for k in SECRETS if os.environ.get(k)}
    try:
        result = execute.with_options(gpu=gpu, timeout=int(timeout_hours * 3600), env=env).remote(
            script, args, run_id, folder
        )
    except Exception as error:  # timeout, out of memory, preempted: keep what it logged, then fail the run
        print(f"lab: the Modal function ended without a result ({error}); collecting what it logged", file=sys.stderr)
        result = {"code": 1, "files": collect.remote(folder)}
    if here is not None:
        unpack(result["files"], here)
    if result["code"] != 0:
        raise SystemExit(result["code"])
