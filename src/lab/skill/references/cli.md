# lab CLI reference

Generated from the code by `scripts/skill_reference.py`; if this disagrees with `lab <cmd> --help`, the CLI wins.


```
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
```

## lab init

```
usage: lab init [-h] [dir]

make a folder a lab

positional arguments:
  dir

options:
  -h, --help  show this help message and exit
```

## lab sync

```
usage: lab sync [-h]

refresh this lab's agent guidance and lab skill

options:
  -h, --help  show this help message and exit
```

## lab new campaign

```
usage: lab new campaign [-h] [--question QUESTION] [--metric METRIC]
                        [--goal {min,max}] [--target TARGET] [--budget BUDGET]
                        name

a question, its metric and its budget

positional arguments:
  name

options:
  -h, --help           show this help message and exit
  --question QUESTION
  --metric METRIC
  --goal {min,max}
  --target TARGET      the value that answers the question, e.g. a published
                       number
  --budget BUDGET
```

## lab new exp

```
usage: lab new exp [-h] [--from SOURCE | -t TEMPLATE] name

an experiment folder, empty, from a template or branched from a run

positional arguments:
  name

options:
  -h, --help            show this help message and exit
  --from SOURCE         an experiment name or a run id to branch from
  -t, --template TEMPLATE
                        start from <lab>/templates/<name> (see `lab
                        templates`)
```

## lab templates

```
usage: lab templates [-h] [--json]

list experiment templates

options:
  -h, --help  show this help message and exit
  --json      print JSON
```

## lab run

```
usage: lab run [-h] [-H HYPOTHESIS] [-P PREDICTION] [--parent PARENT] [-e EXP]
               [-t TAG] [-d]
               ...

run a command and record it

positional arguments:
  command

options:
  -h, --help            show this help message and exit
  -H, --hypothesis HYPOTHESIS
                        what this run tests, as a sentence
  -P, --prediction PREDICTION
                        what you expect, written before the result
  --parent PARENT       run this one builds on (default: previous run of this
                        experiment)
  -e, --exp EXP         experiment name (default: the one around the current
                        directory)
  -t, --tag TAG
  -d, --detach          run in the background, so it outlives this terminal or
                        agent
```

## lab status

```
usage: lab status [-h] [--json]

the campaign at a glance

options:
  -h, --help  show this help message and exit
  --json      print JSON
```

## lab ls

```
usage: lab ls [-h] [--json]
              [--verdict {keep,revert,inconclusive,failed,none,running}]
              [--exp EXP] [-n N] [--tree]

list the campaign's runs

options:
  -h, --help            show this help message and exit
  --json                print JSON
  --verdict {keep,revert,inconclusive,failed,none,running}
                        only runs with it
  --exp EXP             only this experiment's runs
  -n, --last N          only the last N runs
  --tree                lineage order: children under their parent
```

## lab show

```
usage: lab show [-h] [--json] run

one run: result, claim, lineage, files, command, code change

positional arguments:
  run

options:
  -h, --help  show this help message and exit
  --json      print JSON
```

## lab compare

```
usage: lab compare [-h] [--json] [--all] a [b]

two runs side by side

positional arguments:
  a
  b           default: a's parent

options:
  -h, --help  show this help message and exit
  --json      print JSON
  --all       also the attributes that are the same
```

## lab verdict

```
usage: lab verdict [-h] [-m NOTE] [--force]
                   run {keep,revert,inconclusive,failed}

judge a run; keep makes it the baseline

positional arguments:
  run
  {keep,revert,inconclusive,failed}

options:
  -h, --help            show this help message and exit
  -m, --note NOTE       why, in two or three plain sentences
  --force               close a run lab thinks is running but you know has
                        ended
```

## lab lock

```
usage: lab lock [-h] --accept WHY

accept a change to locked/ and start a new comparison epoch

options:
  -h, --help    show this help message and exit
  --accept WHY
```

## lab budget

```
usage: lab budget [-h] [--json]

recorded spend against the cap

options:
  -h, --help  show this help message and exit
  --json      print JSON
```

## lab cost

```
usage: lab cost [-h] -m NOTE [--total] run usd

record what a service billed for a run, e.g. a RunPod bill that posted later

positional arguments:
  run
  usd

options:
  -h, --help       show this help message and exit
  -m, --note NOTE  where the amount comes from, e.g. 'runpodctl billing pods'
  --total          make this the run's whole cost, replacing what was logged
```

## lab board

```
usage: lab board [-h] [--out OUT] [--open]

write the board: one HTML page over every campaign

options:
  -h, --help  show this help message and exit
  --out OUT   output directory (default: <lab>/board)
  --open      open it in the browser
```

## lab bench

```
usage: lab bench [-h] --tasks TASKS [--model-type MODEL_TYPE]
                 [--model-args MODEL_ARGS] [--limit LIMIT]
                 [--num-fewshot NUM_FEWSHOT] [--extra EXTRA] [-H HYPOTHESIS]
                 [-P PREDICTION] [--parent PARENT]
                 model

run lm-evaluation-harness as a recorded run (accuracy + calibration)

positional arguments:
  model                 HF id or local path (or served model name with
                        --model-type local-completions)

options:
  -h, --help            show this help message and exit
  --tasks TASKS         comma-separated lm-eval tasks, e.g.
                        gpqa_diamond_zeroshot,mmlu_pro
  --model-type MODEL_TYPE
                        lm-eval --model: hf, vllm, local-completions, ...
  --model-args MODEL_ARGS
                        extra lm-eval model_args, e.g.
                        dtype=bfloat16,peft=path
  --limit LIMIT         examples per task (or fraction) for a quick look
  --num-fewshot NUM_FEWSHOT
  --extra EXTRA         more lm_eval flags, quoted
  -H, --hypothesis HYPOTHESIS
  -P, --prediction PREDICTION
  --parent PARENT
```

## lab fetch

```
usage: lab fetch [-h] [--include INCLUDE] {model,dataset} repo

download a HF model or dataset at a pinned revision

positional arguments:
  {model,dataset}
  repo               org/name[@revision]

options:
  -h, --help         show this help message and exit
  --include INCLUDE  only files matching this glob (repeatable)
```

## lab doctor

```
usage: lab doctor [-h] [--json]

check tools, keys, logins and skills; exits 1 if something needs fixing

options:
  -h, --help  show this help message and exit
  --json      print JSON
```

## lab smoke

```
usage: lab smoke [-h] [--live] [--only ONLY [ONLY ...]]

run templates on tiny configs to catch breakage

options:
  -h, --help            show this help message and exit
  --live                also check Tinker imports, Prime and Modal auth
  --only ONLY [ONLY ...]
                        template or service names
```

## lab report

```
usage: lab report [-h] [--out OUT] [--open] [name]

write an interactive report page for a campaign

positional arguments:
  name        campaign name or a unique prefix (default: -c, or the one around
              here)

options:
  -h, --help  show this help message and exit
  --out OUT   output directory (default: <lab>/reports)
  --open
```
