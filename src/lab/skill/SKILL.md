---
name: lab
description: Operate the `lab` research CLI - campaigns, `lab run` records, verdicts and baselines, locked evals, budgets, templates, lab.fig figures, the board, lm-eval benches, pinned downloads, Modal and SSH runners, smoke checks, and interactive reports. Use whenever a `lab.toml` is above the working directory or `lab` is on PATH, when the user mentions the lab, a campaign, a run id like r012, the board or a report, or asks to set up a new lab.
metadata:
  version: "1.1.0"
---

# lab

`lab` wraps any command, records every run, and keeps comparisons honest. This skill is how to drive it; how to do the research is `ml-research`, where to run it is `ml-compute`, interpretability methods are `mech-interp`.

## Get oriented first

- `lab doctor` says which services are ready (Tinker key, Prime login, Modal, RunPod, Hugging Face, disk). Run it before promising a route.
- `lab status` (or plain `lab` inside a campaign; elsewhere `lab -c <name> status`) is the first call: the question, the best kept result against the target, the gain over noise, spend, Next, and the last runs.
- `lab ls` lists runs with their result, Δ against the parent and its size in noise floors, and the verdict (the baseline says so); `--verdict`, `--exp`, `-n N` and `--tree` narrow it. `lab show r012` is one run in full; `lab compare r012 [r009]` puts two side by side with the command and code change. Run ids can be typed as `12` or `r12`.
- Piped, every command prints plain text and tables as tab-separated rows; add `--json` to any read command (`status`, `ls`, `show`, `compare`, `budget`, `templates`, `doctor`) when you parse the output. `lab show <run> --json` is the raw record.
- Read the campaign's `campaign.toml` (question, metric, goal, budget, noise floor) and `findings.md` before proposing the next run.

## The cycle

```bash
lab new campaign <name> --metric val_loss --goal min --budget 25 --question "..."
lab new exp <name> --template interp        # or --from r012 to branch from a run's exact code
lab run -H "hypothesis" -P "prediction" -- python train.py --lr 3e-4
lab verdict r013 keep|revert|inconclusive|failed -m "why"
lab board --open                            # what the user looks at
```

A run longer than a few minutes goes in the background with `lab run -d ...`, so it outlives your terminal, chat turn or session; `lab ls` shows when it ends and `runs/<id>/stdout.log` has its output. Judge it once it has ended.

Inside the code: `from lab import log, summary, cost, artifact, fig`. Log curves with `log(step=..., **values)`, the numbers the run is judged by with `summary(...)`, off-machine spend with `cost(usd, note)`, and figures with `fig.<type>(...)`. Outside `lab run` they do nothing, so scripts still run standalone.

## Showing results

- When you report, lead with the deliverable: the latest result against what the question asked for (the number, its run id, the figure), then the one next step. History and failed attempts only when asked, or when they change the next step.
- Everything you write into a record (`-H`, `-P`, `-m`, findings) is read by a person on the board. Write plain sentences: spaces between words and numbers, units on numbers, one claim per sentence ("208 of 256 dev items correct (81.3%), against 108 for the heuristic"), not packed notation ("Verified208/256=81.25% dev vs108/256"). A verdict note is two or three sentences; longer evidence goes in an artifact the note names.
- Keep `findings.md` current as bullets of one sentence each, citing runs (details belong in the run's verdict note; Markdown works): the one or two next steps under "Next", and what the evidence says under "What we believe now". The board and report read only those bullets. When the question has a number to hit (a published result, a threshold), set `target` in `campaign.toml` (or `--target` on `lab new campaign`).
- `lab board --open` is the page to show: every campaign, its runs with curves, figures, code diffs and verdicts. Point the user at it (the path it prints) whenever they ask how things are going.
- `lab report <campaign> --open` is only for sharing or publishing a finding: a page from `report.md` (or, without one, the result, next steps and findings). Do not use it as a status page; that is the board.
- Figures come from the run that produced the numbers: `log(step=..., loss=...)` during training draws its curve, and `fig.<type>(...)` at the end of the script draws comparisons. Do not add a run only to draw a chart, and do not redraw lab results as a chat chart.

## Rules of thumb

- Put data prep and the evaluator in the campaign's `locked/` before the first run; it is hashed then. If it changes later, runs are marked not comparable until `lab lock --accept "why"`, which is for a deliberate, reported change only.
- Judge each run before starting the next: `keep` moves the baseline that comparisons and new experiments start from. A run's parent defaults to the previous run of the same experiment; pass `--parent` when it builds on something else.
- Branch with `lab new exp <name> --from <run>` instead of copying files, so the board can diff code against the parent.
- A helper used by a second experiment belongs in the lab's `lib/` (on every run's path, snapshotted and hashed per run).
- Set `noise_floor` in `campaign.toml` once seeds have measured it, so deltas inside it read as within noise, and only changes of at least 2× it are called likely real.
- Reproducing someone else's repo: clone it into the experiment folder at a pinned commit, without its old outputs, so the snapshot holds the code that ran and the runners ship it; copy its eval and data splits into `locked/`. Outputs go to the run (`LAB_RUN_DIR`, `artifact()`), not to folders beside the campaign.
- Remote machines go through `lab.ssh_app` or `lab.modal_app`, with the host passed as arguments, not a hand-written SSH script with the address in it. A RunPod pod: create it with `runpodctl pod create --terminate-after <time>`, run through `lab.ssh_app`, delete it after (`ml-compute` has the steps).
- Money: the budget counts only amounts a service reported. Never pass a rate × time estimate to `cost()`. When a bill posts after the run, record it with `lab cost <run> <usd> -m "runpodctl billing pods --pod-id ..."` (`--total` replaces an earlier amount). A machine shared by several runs: record its bill once, on the last run that used it, and name the other runs in the note. Paid services start with the smallest config.

## When something is off

- **Budget refusal:** the campaign's `cost_usd` total reached `budget_usd`. Raise it in `campaign.toml` only if the user agrees.
- **"locked/ changed" warning:** someone edited the eval. Find out whether it was intended before accepting.
- **Run shown as `lost`:** its `lab` process was killed hard. A script started by `lab.ssh_app` may still be running or finished on the machine, in the folder it printed at the start (`<root>/<campaign>-<run id>-<suffix>/`): copy its `run/` folder into `runs/<id>/` if you want its results, then judge the run, which closes it with whatever it logged. Otherwise judge it `failed` and rerun with `-d`.
- **`lab verdict` says the run is still running:** wait for it (`lab ls`). If you know its process is gone (another machine, or an old record), `--force` closes it as killed.
- **Command not found / service errors:** `lab doctor`; for templates that stopped working, `lab smoke` (add `--live` for services).
- **Report figure errors:** figure names are file stems in `runs/<id>/figures/`; the error lists the ones that exist.

## New lab

If `lab` is not on PATH: `uv tool install git+https://github.com/esceptico/lab`. `lab init <dir>` makes a folder a lab: `lab.toml`, `campaigns/`, `lib/`, agent guidance (`AGENTS.md`, `CLAUDE.md`) and this skill. After upgrading `lab`, `lab sync` refreshes the last two. A lab's own `templates/<name>/` adds or overrides templates; set `LAB_HOME` when working outside the folder. For interpretability, `from lab import interp` has the hooks, Jacobians and ablations the `interp` template uses (signatures in running.md).

## Reference

- [cli.md](references/cli.md): every command and flag (generated from `--help`).
- [figures.md](references/figures.md): all ten `lab.fig` chart types with signatures and examples.
- [running.md](references/running.md): logging helpers and environment, templates, Modal and SSH runners, bench, reports, `lab.interp`.

These are generated from the code (`scripts/skill_reference.py` in the lab repo); when they disagree with `lab <cmd> --help`, trust the CLI and regenerate.
