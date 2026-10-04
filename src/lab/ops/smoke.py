"""`lab smoke`: run each local template on a tiny config in a throwaway lab, and optionally ping the services."""

import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..core import campaigns, runs
from ..core.store import Campaign, Lab, LabError
from .doctor import command_output

MARKS = {True: "ok  ", False: "FAIL", None: "--  "}
FAILURES_DIR = "smoke-failures"


@dataclass(frozen=True)
class Case:
    template: str
    command: list[str]
    expects: tuple[str, ...]  # summary keys the run must report


CASES = [
    Case("modal-custom", ["uv", "run", "--no-project", "--with", "torch", "python", "train.py", "--steps", "40"], ("val_loss", "val_acc")),
    Case(
        "interp",
        ["uv", "run", "--no-project", "--with", "torch", "--with", "transformers>=4.56", "python", "experiment.py",
         "--model", "sshleifer/tiny-gpt2", "--src", "0", "--dst", "1", "--k", "1", "--prompts", "1", "--random-seeds", "2"],
        ("loss_increase", "vs_random"),
    ),
]  # fmt: skip

SERVICES = {
    "tinker-sft": ["uv", "run", "--no-project", "--with", "tinker", "--with", "tinker-cookbook", "python", "-c",
                   "import tinker, tinker_cookbook.supervised.data, tinker_cookbook.renderers"],
    "prime-rl": ["prime", "train", "models", "-o", "json"],
    "modal": ["modal", "app", "list"],
}  # fmt: skip


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool | None  # None: skipped
    seconds: float
    detail: str


def run(lab: Lab, only: list[str] | None = None, live: bool = False) -> list[Result]:
    def selected(name: str) -> bool:
        return not only or name in only

    known = {c.template for c in CASES} | set(SERVICES)
    if unknown := sorted(set(only or []) - known):
        raise LabError(f"no smoke check {', '.join(unknown)}; checks: {', '.join(sorted(known))}")
    if only and not live and not {c.template for c in CASES} & set(only):
        raise LabError(f"{', '.join(only)} {'is a service' if len(only) == 1 else 'are services'}: add --live")

    results = []
    with tempfile.TemporaryDirectory(prefix="lab-smoke-") as tmp:
        scratch = Lab(Path(tmp))
        (scratch.root / "lab.toml").write_text("")
        scratch.templates.symlink_to(lab.templates)
        scratch.lib.symlink_to(lab.lib)
        campaign = campaigns.create_campaign(scratch, "smoke", metric="val_loss", budget_usd=None)
        for case in CASES:
            if selected(case.template):
                results.append(template_case(lab, scratch, campaign, case))
    if live:
        results += [service(name, command) for name, command in SERVICES.items() if selected(name)]
    return results


def template_case(lab: Lab, scratch: Lab, campaign: Campaign, case: Case) -> Result:
    started = time.monotonic()
    experiment = campaigns.create_experiment(scratch, campaign, case.template, template=case.template)
    run = runs.start(
        scratch,
        campaign,
        runs.RunRequest(experiment, case.command, f"smoke {case.template}", quiet=True),
        notify=lambda _: None,
    )
    missing = [key for key in case.expects if key not in run.metrics]
    ok = run.exit_code == 0 and not missing
    detail = "ok"
    if not ok:
        kept = lab.root / FAILURES_DIR / case.template
        shutil.copytree(campaign.run_dir(run.id), kept, dirs_exist_ok=True)
        detail = str(run.status) + (f", missing {missing}" if missing else "") + f" · kept in {kept}"
    return Result(case.template, ok, time.monotonic() - started, detail)


def service(name: str, command: list[str]) -> Result:
    if not shutil.which(command[0]):
        return Result(name, None, 0.0, f"{command[0]} not installed")
    started = time.monotonic()
    code, text = command_output(command, timeout=300)
    last = text.splitlines()[-1][:160] if text else f"exit {code}, no output"
    return Result(name, code == 0, time.monotonic() - started, "" if code == 0 else last)
