# prime-rl

RL (or SFT distillation) on Prime Intellect Hosted Training, recorded as a lab run.

- `rl.toml`: the hosted config (model, steps, batch, rollouts, env from the Environments Hub,
  online eval). Change it per experiment; the diff shows on the board.
- `run.py`: launches `prime train rl.toml`, polls status, then logs all metric records by step,
  `summary(<metric>=last value)`, the real cost from `prime train usage`, and saves the run
  record as an artifact. Ctrl-C detaches and leaves the hosted run going.

Setup: `prime login` once (and `prime upgrade`; configs follow CLI 0.7). Custom reward or env:
write a verifiers environment, push it to the Hub, point `[[env]] id` at it.

```bash
lab run -H "RL on reverse-text lifts eval reward" -P "reward > 0.6 by step 100" -- \
  python run.py rl.toml --metric reward
```
Set the campaign `metric` to the same key (e.g. `metric = "reward"`, `goal = "max"`).
Prime prices by tokens: see `prime train models` before raising `max_steps`.
