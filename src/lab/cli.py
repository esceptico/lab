"""lab: run anything, record every run, compare honestly."""

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from .core import campaigns, compare, runs
from .core.model import Run, Verdict
from .core.store import Campaign, Lab, LabError
from .ops import bench, doctor, fetch, smoke, workspace
from .views import board, report, text

GUIDE = """\
lab: run anything, record every run, compare honestly.

Start
  init [dir]                       make a folder a lab: lab.toml, campaigns/, lib/, agent guidance, the skill
  sync                             refresh the lab's agent guidance and skill after upgrading lab
  new campaign <name> --metric M --goal min|max [--question Q] [--target T] [--budget USD]
  new exp <name> [--from <exp|run> | --template <t>]
  templates                        the experiment templates

Run
  run -H "hypothesis" -P "prediction" [-d] -- <command>
  verdict <run> keep|revert|inconclusive|failed -m "why"
  cost <run> <usd> -m "where the amount comes from" [--total]
  lock --accept "why the eval changed"

Inspect
  status                           the campaign at a glance: result against target, Next, last runs
  ls [--verdict V] [--exp E] [-n N] [--tree]
  show <run>                       one run: result, claim, lineage, files, command, code change
  compare <a> [<b>]                two runs side by side (b defaults to a's parent)
  budget                           spend against the cap

Share
  board [--open]                   one page over every campaign
  report [campaign] [--open]       a page for sharing a finding

Machines and data
  bench <model> --tasks a,b        lm-evaluation-harness as a recorded run
  fetch model|dataset <repo>[@rev] download at a pinned revision
  doctor                           which tools, keys and logins are ready
  smoke [--live]                   run the templates on tiny configs

Inside a campaign folder -c is not needed, and `lab` alone is `lab status` (at the lab's root: its campaigns). Run ids: 9, r9 and r009 are
the same run. Results go to stdout; progress, warnings and next steps go to stderr. On a terminal output
is coloured and fitted to the width; piped, it is plain and tables are tab-separated. Every read command
takes --json. `lab <command> --help` has every option.
"""

# What an error shows after the usage line, so the caller sees a working command.
EXAMPLES = {
    "init": "lab init my-lab",
    "new campaign": 'lab new campaign speedrun --metric val_loss --goal min --budget 25 --question "..."',
    "new exp": "lab new exp wider --from r012",
    "run": 'lab run -H "lr 3e-4 beats 1e-3" -P "val_loss under 3.30" -- python train.py --lr 3e-4',
    "ls": "lab ls --verdict keep -n 10",
    "show": "lab show r012",
    "compare": "lab compare r012 r009",
    "verdict": 'lab verdict r012 keep -m "beats r009 by 2.4x noise"',
    "lock": 'lab lock --accept "fixed a label leak in the dev split"',
    "cost": 'lab cost r012 4.20 -m "runpodctl billing pods --pod-id abc123"',
    "report": "lab report --open",
    "bench": "lab bench Qwen/Qwen3-0.6B --tasks arc_easy --limit 50",
    "fetch": "lab fetch model Qwen/Qwen3-0.6B@main",
    "smoke": "lab smoke --only tinker-sft",
}
RUN_REF = re.compile(r"r?0*(\d+)")
RUN = 'lab run -H "hypothesis" -P "prediction" -- <command>'


def judge(run_id: str) -> str:
    return f'lab verdict {run_id} keep|revert|inconclusive|failed -m "why"'


class Parser(argparse.ArgumentParser):
    """argparse with lab's errors: what is wrong, the usage line, a working example, where the options are."""

    def error(self, message: str) -> None:
        name = self.prog.removeprefix("lab").strip()
        message = message.replace("the following arguments are required:", "missing").replace("argument ", "")
        if message.startswith("unrecognized arguments"):
            message += ' (text with spaces needs quotes: -m "two words")'
        if wrong := re.match(r"command: invalid choice: '([^']*)' \(choose from (.*)\)", message):
            near = difflib.get_close_matches(wrong[1], wrong[2].split(", "), n=1)
            message = f"no command {wrong[1]!r}" + (f"; did you mean `lab {near[0]}`?" if near else "")
        print(f"{self.prog}: {message}", file=sys.stderr)
        print(self.format_usage().strip(), file=sys.stderr)
        if name in EXAMPLES:
            print(f"  e.g. {EXAMPLES[name]}", file=sys.stderr)
        print(f"  {self.prog} --help lists every option", file=sys.stderr)
        sys.exit(2)


def run_ref(value: str) -> str:
    """A run id as people type it: 9, r9 and r009 are all r009."""
    match = RUN_REF.fullmatch(value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(f"{value!r} is not a run id (like r012, or 12)")
    return f"r{int(match[1]):03d}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return getattr(args, "handler", cmd_home)(args) or 0
    except LabError as error:
        print(f"lab: error: {error}", file=sys.stderr)
        return 1


def build_parser() -> Parser:
    parser = Parser(prog="lab", usage="lab [-c campaign] [--json] <command> ...", add_help=False)
    parser.format_help = lambda: GUIDE  # the grouped guide above; argparse's own list would repeat it
    parser.add_argument("-h", "--help", action="help", help=argparse.SUPPRESS)
    parser.add_argument("-c", "--campaign", help="campaign name or a unique prefix of it")
    parser.add_argument("--json", action="store_true", help="structured output from a read command")
    sub = parser.add_subparsers(metavar="command", parser_class=Parser, prog="lab")

    def command(name: str, about: str, handler, json: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name, description=about)
        if json:  # `lab ls --json` and `lab --json ls` both work; SUPPRESS keeps the subcommand from resetting it
            p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON")
        p.set_defaults(handler=handler)
        return p

    command("init", "make a folder a lab", cmd_init).add_argument("dir", nargs="?", default=".")
    command("sync", "refresh this lab's agent guidance and lab skill", cmd_sync)

    new = sub.add_parser("new", description="create a campaign or an experiment").add_subparsers(
        required=True, metavar="campaign|exp", parser_class=Parser, prog="lab new"
    )
    p = new.add_parser(
        "campaign", help="a question, its metric and its budget", description="a question, its metric and its budget"
    )
    p.add_argument("name")
    p.add_argument("--question", default="")
    p.add_argument("--metric", default="val_loss")
    p.add_argument("--goal", choices=("min", "max"), default="min")
    p.add_argument("--target", type=float, help="the value that answers the question, e.g. a published number")
    p.add_argument("--budget", type=float, default=25.0)
    p.set_defaults(handler=cmd_new_campaign)
    about = "an experiment folder, empty, from a template or branched from a run"
    p = new.add_parser("exp", help=about, description=about)
    p.add_argument("name")
    source = p.add_mutually_exclusive_group()
    source.add_argument("--from", dest="source", help="an experiment name or a run id to branch from")
    source.add_argument("-t", "--template", help="start from <lab>/templates/<name> (see `lab templates`)")
    p.set_defaults(handler=cmd_new_exp)

    command("templates", "list experiment templates", cmd_templates, json=True)

    p = command("run", "run a command and record it", cmd_run)
    p.add_argument("-H", "--hypothesis", default="", help="what this run tests, as a sentence")
    p.add_argument("-P", "--prediction", default="", help="what you expect, written before the result")
    p.add_argument("--parent", type=run_ref, help="run this one builds on (default: previous run of this experiment)")
    p.add_argument("-e", "--exp", help="experiment name (default: the one around the current directory)")
    p.add_argument("-t", "--tag", action="append", default=[])
    p.add_argument(
        "-d", "--detach", action="store_true", help="run in the background, so it outlives this terminal or agent"
    )
    p.add_argument("command", nargs=argparse.REMAINDER)

    command("status", "the campaign at a glance", cmd_status, json=True)

    p = command("ls", "list the campaign's runs", cmd_ls, json=True)
    p.add_argument("--verdict", choices=[*[v.value for v in Verdict], "none", "running"], help="only runs with it")
    p.add_argument("--exp", help="only this experiment's runs")
    p.add_argument("-n", "--last", type=int, metavar="N", help="only the last N runs")
    p.add_argument("--tree", action="store_true", help="lineage order: children under their parent")

    p = command("show", "one run: result, claim, lineage, files, command, code change", cmd_show, json=True)
    p.add_argument("run", type=run_ref)

    p = command("compare", "two runs side by side", cmd_compare, json=True)
    p.add_argument("a", type=run_ref)
    p.add_argument("b", type=run_ref, nargs="?", help="default: a's parent")
    p.add_argument("--all", action="store_true", help="also the attributes that are the same")

    p = command("verdict", "judge a run; keep makes it the baseline", cmd_verdict)
    p.add_argument("run", type=run_ref)
    p.add_argument("verdict", choices=[v.value for v in Verdict])
    p.add_argument("-m", "--note", default="", help="why, in two or three plain sentences")
    p.add_argument("--force", action="store_true", help="close a run lab thinks is running but you know has ended")

    p = command("lock", "accept a change to locked/ and start a new comparison epoch", cmd_lock)
    p.add_argument("--accept", required=True, metavar="WHY")

    command("budget", "recorded spend against the cap", cmd_budget, json=True)

    p = command("cost", "record what a service billed for a run, e.g. a RunPod bill that posted later", cmd_cost)
    p.add_argument("run", type=run_ref)
    p.add_argument("usd", type=float)
    p.add_argument("-m", "--note", required=True, help="where the amount comes from, e.g. 'runpodctl billing pods'")
    p.add_argument("--total", action="store_true", help="make this the run's whole cost, replacing what was logged")

    p = command("board", "write the board: one HTML page over every campaign", cmd_board)
    p.add_argument("--out", help="output directory (default: <lab>/board)")
    p.add_argument("--open", action="store_true", help="open it in the browser")

    p = command("bench", "run lm-evaluation-harness as a recorded run (accuracy + calibration)", cmd_bench)
    p.add_argument("model", help="HF id or local path (or served model name with --model-type local-completions)")
    p.add_argument("--tasks", required=True, help="comma-separated lm-eval tasks, e.g. gpqa_diamond_zeroshot,mmlu_pro")
    p.add_argument("--model-type", default="hf", help="lm-eval --model: hf, vllm, local-completions, ...")
    p.add_argument("--model-args", default="", help="extra lm-eval model_args, e.g. dtype=bfloat16,peft=path")
    p.add_argument("--limit", type=float, help="examples per task (or fraction) for a quick look")
    p.add_argument("--num-fewshot", type=int)
    p.add_argument("--extra", default="", help="more lm_eval flags, quoted")
    p.add_argument("-H", "--hypothesis", default="")
    p.add_argument("-P", "--prediction", default="")
    p.add_argument("--parent", type=run_ref)

    p = command("fetch", "download a HF model or dataset at a pinned revision", cmd_fetch)
    p.add_argument("kind", choices=["model", "dataset"])
    p.add_argument("repo", help="org/name[@revision]")
    p.add_argument("--include", action="append", help="only files matching this glob (repeatable)")

    command("doctor", "check tools, keys, logins and skills; exits 1 if something needs fixing", cmd_doctor, json=True)

    p = command("smoke", "run templates on tiny configs to catch breakage", cmd_smoke)
    p.add_argument("--live", action="store_true", help="also check Tinker imports, Prime and Modal auth")
    p.add_argument("--only", nargs="+", help="template or service names")

    p = command("report", "write an interactive report page for a campaign", cmd_report)
    p.add_argument("name", nargs="?", help="campaign name or a unique prefix (default: -c, or the one around here)")
    p.add_argument("--out", help="output directory (default: <lab>/reports)")
    p.add_argument("--open", action="store_true")
    return parser


def context(args) -> tuple[Lab, Campaign, Path | None]:
    lab = Lab.find()
    if args.campaign:
        return lab, find_campaign(lab, args.campaign), None
    campaign, experiment = lab.locate()
    return lab, campaign, experiment


def find_campaign(lab: Lab, name: str) -> Campaign:
    """The campaign by name, or by a prefix only one campaign has; the expansion is reported on stderr."""
    names = [c.name for c in lab.campaigns()]
    matches = [n for n in names if n == name] or [n for n in names if n.startswith(name)]
    if len(matches) != 1:
        found = "matches " + ", ".join(matches) if matches else "is not a campaign"
        raise LabError(f"{name!r} {found}; campaigns: {', '.join(names) or 'none yet'}")
    if matches[0] != name:
        print(f"lab: -c {name} → {matches[0]}", file=sys.stderr)
    return lab.campaign(matches[0])


def emit(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def exit_code(run: Run) -> int:
    return 0 if run.exit_code == 0 else run.exit_code or 1


def shown(path: Path) -> str:
    """The path relative to here when it is below here, so next-step commands stay short."""
    return str(path.relative_to(Path.cwd())) if path.is_relative_to(Path.cwd()) else str(path)


def hint(message: str) -> None:
    sys.stdout.flush()  # so the next step prints after the result it follows
    print(f"next: {message}", file=sys.stderr)


def cmd_init(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    changes = workspace.init(root)
    print(f"created a lab in {root}: {', '.join(changes.written)}")
    if changes.kept:
        print(f"kept your {', '.join(changes.kept)}; agents still load the lab skill from .claude/skills/lab/")
    enter = "" if root == Path.cwd().resolve() else f"cd {shown(root)} && "
    hint(f'{enter}lab new campaign <name> --metric <metric> --goal min|max --question "..."')


def cmd_sync(args) -> None:
    changes = workspace.sync(Lab.find().root)
    print(f"refreshed {', '.join(changes.written)}")
    if changes.kept:
        print(f"kept {', '.join(changes.kept)}: its 'managed by lab' line was removed, so your edits stay")


def cmd_new_campaign(args) -> None:
    campaign = campaigns.create_campaign(
        Lab.find(),
        args.name,
        question=args.question,
        metric=args.metric,
        goal=args.goal,
        budget_usd=args.budget,
        target=args.target,
    )
    print(f"created campaign {campaign.name} in {shown(campaign.root)}")
    hint(
        f"put data prep and the eval in {shown(campaign.locked)}/, then: lab -c {campaign.name} new exp <name> [--template <t>]"
    )


def cmd_new_exp(args) -> None:
    lab, campaign, _ = context(args)
    source = run_ref(args.source) if args.source and RUN_REF.fullmatch(args.source) else args.source  # 9 is r009
    path = campaigns.create_experiment(lab, campaign, args.name, template=args.template, source=source)
    origin = f" from template {args.template}" if args.template else f" from {args.source}" if args.source else ""
    print(f"created experiment {args.name}{origin} in {shown(path)}")
    hint(f"cd {shown(path)} && {RUN}")


def cmd_templates(args) -> None:
    found = campaigns.templates(Lab.find())
    if args.json:
        emit([{"name": t.name, "summary": t.summary, "custom": t.custom} for t in found])
        return
    for template in found:
        print(f"{template.name:<14} {template.summary}" + ("  (this lab's)" if template.custom else ""))
    hint("lab new exp <name> --template <template>")


def cmd_run(args) -> int:
    lab, campaign, experiment = context(args)
    if args.exp:
        experiment = campaign.experiment(args.exp)
    if experiment is None:
        raise LabError("run from inside an experiment folder, or pass -e <experiment>")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.detach:  # the same run, rebuilt from what was parsed: never re-reads -d, abbreviated or combined
        again = ["-c", campaign.name, "run", "-H", args.hypothesis, "-P", args.prediction, "-e", experiment.name]
        again += [*(["--parent", args.parent] if args.parent else []), *(f"--tag={t}" for t in args.tag)]
        return run_detached(campaign, [*again, "--", *command])
    request = runs.RunRequest(experiment, command, args.hypothesis, args.prediction, args.parent, tuple(args.tag))
    return ended(campaign, runs.start(lab, campaign, request))


def ended(campaign: Campaign, run: Run) -> int:
    print(text.result_line(campaign, run))
    if run.exit_code:
        print(f"  output: {shown(campaign.run_dir(run.id) / 'stdout.log')}")
    hint(judge(run.id))
    return exit_code(run)


def run_detached(campaign: Campaign, argv: list[str]) -> int:
    """Start `lab <argv>` (a run without -d) in its own session and return once the command is running."""
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(
            [sys.executable, "-m", "lab.cli", *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            start_new_session=True,  # a signal to this terminal's or agent's process group does not reach it
        )
        started = None
        while started is None and child.poll() is None:
            time.sleep(0.2)
            started = next((r for r in campaign.runs() if r.pid == child.pid), None)
            if started and not (campaign.run_dir(started.id) / "stdout.log").exists():
                started = None  # still snapshotting; its warnings are not all written yet
        errors.seek(0)
        sys.stderr.buffer.write(errors.read())
    if started is None:  # it ended before the command started: refused (budget, bad option) or ran instantly
        return child.returncode
    print(f"{started.id} running in the background")
    print(f"  output: {shown(campaign.run_dir(started.id) / 'stdout.log')}")
    hint(f"`lab ls` shows when it ends; then {judge(started.id)}")
    return 0


def cmd_home(args) -> None:
    """Bare `lab`: the campaign around here (or -c), the campaigns at a lab's root, the guide outside a lab."""
    try:
        lab = Lab.find()
    except LabError:
        print(GUIDE, end="")
        return
    if not args.campaign:
        try:
            lab.locate()
        except LabError:
            print(text.campaigns(lab))
            hint("cd campaigns/<name> (or lab -c <name>) for one campaign; lab --help for every command")
            return
    cmd_status(args)


def cmd_status(args) -> None:
    _, campaign, _ = context(args)
    if args.json:
        emit(text.status_data(campaign))
        return
    print(text.status(campaign))
    hint(
        "lab show <run> for one run; lab board --open for the page"
        if campaign.runs()
        else f"from an experiment folder: {RUN}"
    )


def cmd_ls(args) -> None:
    _, campaign, _ = context(args)
    if args.json:
        emit(text.ls_data(campaign, args.verdict, args.exp, args.last))
        return
    print(text.ls(campaign, args.verdict, args.exp, args.last, args.tree))
    recorded = campaign.runs()
    if not recorded:
        hint(f"from an experiment folder: {RUN}")
    elif any(runs.lost(run) for run in recorded):
        hint("a lost run's lab process ended without a result (killed hard): judge it to close it")


def cmd_show(args) -> None:
    _, campaign, _ = context(args)
    run = campaign.run(args.run)
    if args.json:
        print(run.model_dump_json(indent=2))
        return
    print(text.show(campaign, run))
    hint(f"lab compare {run.id} for the full change; lab show {run.id} --json for the record")


def cmd_compare(args) -> None:
    _, campaign, _ = context(args)
    a = campaign.run(args.a)
    if args.b is None and a.parent is None:
        raise LabError(f"{a.id} has no parent; name the run to compare with: lab compare {a.id} <run>")
    b = campaign.run(args.b or a.parent)
    if args.json:
        emit(text.compare_data(campaign, a, b))
        return
    print(text.compare_text(campaign, a, b, everything=args.all))


def cmd_verdict(args) -> None:
    _, campaign, _ = context(args)
    config, before = campaign.config(), campaign.baseline()
    after = runs.judge(campaign, args.run, Verdict(args.verdict), args.note, force=args.force)
    run = campaign.run(args.run)
    print(text.verdict_line(campaign, run, before, after))
    change = compare.delta(run, before, config.metric) if before and before.id != run.id else None
    x = compare.noise_multiple(change, config) if change is not None else None
    if run.verdict is Verdict.KEEP and x is not None and x < 1:
        sys.stdout.flush()  # the warning follows the line it is about
        print(
            f"lab: warning: {run.id} is kept within noise of {before.id} ({x:.1f}× the noise floor); "
            "say in -m why it is kept anyway",
            file=sys.stderr,
        )


def cmd_cost(args) -> None:
    _, campaign, _ = context(args)
    run = runs.record_cost(campaign, args.run, args.usd, args.note, total=args.total)
    change = "set to" if args.total else "added"
    total = f"; its cost is now ${run.cost_usd:.2f}" if run.finished else "; it counts when the run ends"
    print(f"{run.id}: {change} ${args.usd:.2f} ({args.note}){total}")


def cmd_lock(args) -> None:
    _, campaign, _ = context(args)
    epoch = runs.accept_lock(campaign, args.accept)
    print(f"accepted locked/ as eval epoch {epoch}: runs from here compare only with each other")


def cmd_budget(args) -> None:
    _, campaign, _ = context(args)
    if args.json:
        emit(text.budget_data(campaign))
        return
    print(text.budget(campaign))
    print("lab: counts only what services billed and lab.cost() recorded", file=sys.stderr)


def write_page(path: Path, html: str, open_it: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    print(f"wrote {shown(path)}")
    if open_it:
        webbrowser.open(path.as_uri())
    else:
        hint("add --open to open it in the browser")


def cmd_board(args) -> None:
    lab = Lab.find()
    out = Path(args.out).expanduser().resolve() if args.out else lab.root / "board"
    write_page(out / "index.html", board.render(lab, out), args.open)


def cmd_report(args) -> None:
    lab = Lab.find()
    campaign = find_campaign(lab, args.name) if args.name else context(args)[1]
    out = Path(args.out).expanduser().resolve() if args.out else lab.root / "reports"
    write_page(out / f"{campaign.name}.html", report.render(campaign), args.open)


def cmd_bench(args) -> int:
    lab, campaign, _ = context(args)
    request = bench.BenchRequest(
        args.model, args.tasks, args.model_type, args.model_args, args.limit, args.num_fewshot, args.extra
    )
    run = bench.run(lab, campaign, request, hypothesis=args.hypothesis, prediction=args.prediction, parent=args.parent)
    return ended(campaign, run)


def cmd_fetch(args) -> None:
    lab = Lab.find()
    try:
        pins_dir = lab.locate()[0].root
    except LabError:
        pins_dir = lab.root
    pin = fetch.fetch(args.kind, args.repo, args.include or [], pins_dir)
    size = f"{pin.bytes / 1e9:.2f} GB" if pin.bytes else "size unknown"
    print(f"fetched {pin.kind} {pin.repo} @ {pin.revision[:12]} · license {pin.license or 'not stated'} · {size}")
    print(f"  cached at {pin.path}\n  pinned in {shown(pins_dir / fetch.PINS_FILE)}")
    if not pin.license:
        print("  no license in the card: check the repo before using it in anything you publish")


def cmd_doctor(args) -> int:
    results = doctor.checks()
    if args.json:
        emit([vars(check) for check in results])
    else:
        for check in results:
            print(f"{doctor.MARKS[check.ok]}{check.name:<13} {check.detail}")
            if not check.ok and check.fix:
                print(f"{'':18}→ {check.fix}")
    return 1 if any(check.ok is False for check in results) else 0


def cmd_smoke(args) -> int:
    results = smoke.run(Lab.find(), only=args.only, live=args.live)
    for result in results:
        print(f"{smoke.MARKS[result.ok]} {result.name:<13} {result.seconds:5.0f}s  {result.detail}")
    if not args.live:
        print("(services not checked; add --live to check Tinker imports, Prime and Modal auth)")
    return 0 if all(r.ok is not False for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
