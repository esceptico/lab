# Running, logging, remote machines, reports

Generated from the code by `scripts/skill_reference.py`; if this disagrees with `lab <cmd> --help`, the CLI wins.

## Logging from inside a run

Logging from code running under `lab run`.

    from lab import log, summary, cost, artifact, fig

    log(step=100, loss=0.41, jac_rank=37)   # a point on a curve
    summary(val_loss=0.38)                  # the numbers this run is judged by
    cost(1.20, "tinker sft")                # money spent outside this machine
    artifact("spectrum.png", "Jacobian spectrum, layer 12")

Outside `lab run` every call does nothing, so the same script runs standalone.

This module, `lab.fig`, `lab.events`, `lab.remote`, `lab.ssh_app` and `lab.bench_run` run inside
experiment environments on the standard library alone; `lab.modal_app` needs `modal` and `lab.hf_fetch`
`huggingface_hub`, which their callers install. The CLI's internals live in `lab.core`, `lab.views` and `lab.ops`.

Environment set by `lab run`: `LAB_RUN_DIR`, `LAB_RUN_ID`, `LAB_CAMPAIGN_DIR`, `LAB_LOCKED_DIR`, `LAB_HOME`; `PYTHONPATH` gets the `lab` package (alone, without lab's own dependencies) and `lib/`, so any interpreter or venv can `from lab import ...` and import `lib/` modules. On a remote machine (`lab.ssh_app`, `lab.modal_app`) the script gets `LAB_RUN_DIR`, `LAB_RUN_ID` and `LAB_LOCKED_DIR`, with the package and `lib/` on `PYTHONPATH`.

## Templates

- `interp`: A Jacobian-subspace experiment on any Hugging Face causal LM, with controls built in.
- `modal-custom`: Plain PyTorch you own completely: custom architectures, losses on activations, anything Tinker cannot express. The same script runs locally or on a Modal GPU.
- `prime-rl`: RL (or SFT distillation) on Prime Intellect Hosted Training, recorded as a lab run.
- `tinker-sft`: LoRA supervised fine-tuning on Tinker, with room for your own loss.

Start one with `lab new exp <name> --template <template>`; each folder has a README with the exact command.

## Modal: lab.modal_app

Run any experiment script on a Modal GPU and bring its lab outputs home.

    lab run -H "..." -- modal run -m lab.modal_app --script train.py --args "--lr 3e-4" --gpu A10

The experiment folder, the campaign's locked/ folder and the lab's lib/ are shipped into the
container; `requirements.txt` in the experiment folder is installed into the image (cached).
Inside, the script logs with `lab.log` / `lab.fig` as usual into a folder on the `lab-data` volume,
so what it logged survives the container: when it ends, or dies (timeout, out of memory, preemption),
metrics, figures and artifacts are copied into the local run. Checkpoints belong in $LAB_DATA_DIR
(the same volume), not in artifacts. Cost is not logged: Modal bills your account, and lab records only
amounts a service reports.

Needs `pip install modal` and `modal token new` once.

Options of the local entrypoint: `--script` (default train.py), `--args` (quoted), `--gpu` (T4, L4, A10, L40S, A100-40GB, A100-80GB, H100, H200, B200; `:N` for several), `--timeout-hours` (default 6).

## Any SSH machine: lab.ssh_app

Run an experiment script on any machine you can SSH into (a RunPod or Prime pod, Lambda, your own box).

    lab run -H "..." -- python -m lab.ssh_app --host root@203.0.113.7 --port 22042 \
        --script train.py --args "--lr 3e-4"

Copies the experiment folder, the campaign's locked/, the lab's lib/ and the lab package to
<root>/<campaign>-<run id>-<suffix> with rsync (a folder of its own, printed at the start), installs
requirements.txt if present, and starts the script there detached from the SSH session, so a dropped
connection does not stop it. Its output streams here; if SSH drops, this reconnects for up to
--reconnect-minutes. When the script ends, metrics, figures and artifacts are copied back into the run
and the folder is removed; if they cannot be copied, the folder stays and the run is marked failed.
Ctrl-C or SIGTERM here stops the script on the machine. HF_TOKEN and WANDB_API_KEY are passed in a 0600
env file, not argv, and deleted once the script has read it.
Cost is not logged: lab records only amounts a service reports.
Checkpoints: write them under --root on the machine (a network volume on RunPod), not artifacts.
`--host local` runs the same steps without SSH (for testing the path).

```
usage: ssh_app.py [-h] --host HOST [--port PORT] [--key KEY] [--root ROOT]
                  [--script SCRIPT] [--args ARGS] [--python PYTHON]
                  [--no-setup] [--reconnect-minutes RECONNECT_MINUTES]

options:
  -h, --help            show this help message and exit
  --host HOST           user@host, or 'local'
  --port PORT
  --key KEY             ssh identity file
  --root ROOT           working directory on the machine (relative to home, or
                        absolute)
  --script SCRIPT
  --args ARGS
  --python PYTHON
  --no-setup            skip pip install -r requirements.txt
  --reconnect-minutes RECONNECT_MINUTES
                        how long to retry a dropped connection
```

## Remote outputs: lab.remote

What the SSH and Modal runners share: the folders they ship, and moving a run's outputs back.

Remote code logs into its own scratch run directory (LAB_RUN_DIR there); when it finishes,
`pack` collects what `lab` records and `unpack` merges it into the real run directory here.

## Benchmarks: lab bench

Run lm-evaluation-harness inside a lab run; record every metric, plus ECE and Brier for multiple-choice tasks.

Started by `lab bench`. For multiple-choice tasks, a softmax over the choices' log-likelihoods gives a
probability per choice. The samples format was checked against lm-eval d6de8164: `filtered_resps` holds
[loglikelihood, is_greedy] per choice (written as strings), and `target` is the gold index or answer text.

## Reports: lab report

`lab report <campaign>`: a self-contained interactive page from report.md (or findings.md).

Markdown (CommonMark + tables), plus:
  - run ids (r008) become links that show the run's evidence on hover;
  - a line `{{figure <name> runs=r003,r008,r004 labels="k = 4,k = 8,k = 16" label="k"}}` embeds that
    figure from each listed run; with several runs it becomes a switcher over those recorded runs
    only (compare toggles, steppers), never interpolated;
  - the page ends with the runs cited, what did not work, and how to reproduce each cited run.
Figure names are the file stems in runs/<id>/figures/ (a slug of the figure's title).

## Interpretability helpers: lab.interp

Interpretability helpers for Hugging Face causal LMs. Needs torch and transformers (run-side only).

Residual stream convention: `layer` L means the output of block L (the residual after it).
Everything is plain torch with forward hooks; no TransformerLens or nnsight needed.

### interp.ablate

```python
interp.ablate(model, layer: int, basis: torch.Tensor, position: int | None = None) -> Iterator[None]
```

Project the span of `basis` ([k, d], any rows) out of the residual after block `layer`.

`position=None` ablates every position. A Jacobian taken at one position describes that
position; pass the same `position` to test exactly what it measured.

### interp.blocks

```python
interp.blocks(model: torch.nn.modules.module.Module) -> torch.nn.modules.container.ModuleList
```

The decoder layers: the module list as long as the config's layer count, all of one block class.

### interp.bootstrap

```python
interp.bootstrap(values: torch.Tensor, stat: Callable[[torch.Tensor], torch.Tensor] = mean, n: int = 1000, seed: int = 0)
```

(statistic, low, high): the statistic over `values` and its 95% percentile bootstrap interval.

### interp.jacobian

```python
interp.jacobian(model, tok, text: str, src: int, dst: int, pos: int = -1, vectorize: bool = False) -> torch.Tensor
```

d resid[dst][pos] / d resid[src][pos] for one text: a [d, d] matrix.

The residual at `pos` after block `src` is replaced by a free variable; everything else in
the forward pass is fixed. `vectorize=True` is faster but needs more memory.

### interp.load

```python
interp.load(name: str, device: str | None = None, dtype: torch.dtype | None = None)
```



### interp.next_token_loss

```python
interp.next_token_loss(model, tok, texts: Sequence[str]) -> torch.Tensor
```

Mean next-token loss per text: a [n] tensor (bootstrap over it for intervals).

### interp.random_basis

```python
interp.random_basis(d: int, k: int, seed: int) -> torch.Tensor
```



### interp.resid

```python
interp.resid(model, tok, texts: Sequence[str], layer: int) -> list[torch.Tensor]
```

Residual after block `layer` for each text: a list of [seq, d] tensors (no padding).

Read with a hook on the block output, not `hidden_states`: HF applies the final norm to the
last entry of `hidden_states` (GPT-2's ln_f), which is not the raw residual.

### interp.sae_basis

```python
interp.sae_basis(release: str, sae_id: str, acts: torch.Tensor, k: int) -> torch.Tensor
```

Decoder directions of the k SAE features most active on `acts` ([n, d]). Needs sae_lens.

### interp.spectrum

```python
interp.spectrum(J: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]
```

Singular values and right singular vectors (rows, in the source residual space).
