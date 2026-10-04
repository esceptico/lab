# tinker-sft

LoRA supervised fine-tuning on Tinker, with room for your own loss.

- `train.py`: the loop (cookbook renderer → datums → `forward_backward` + `optim_step`, linear LR
  decay, validation NLL every `--eval-every` steps). Logs `train_nll`, `val_nll`, `lr`, `tokens`
  per step; `summary(val_nll=...)` at the end; prints the sampler weights path.
- `losses.py`: custom losses over logprobs (`--loss weighted_nll`, `--loss focal_nll`, or add yours
  to `CUSTOM`). Limits: logprobs only, no hidden states; `loss_fn_inputs` carries only
  `target_tokens` and `weights`.

Setup: `TINKER_API_KEY` in the environment. Put `train.jsonl` / `val.jsonl` (chat format,
`{"messages": [...]}` per line) in the campaign's `locked/` so the eval data is hashed.
Tokens trained are logged per step (`tokens`); Tinker bills your account, and lab records no cost.

```bash
lab run -H "SFT on 2k decision prompts" -P "val_nll drops ~0.1" -- \
  uv run --with tinker --with tinker-cookbook python train.py --model Qwen/Qwen3-8B
```
Set the campaign `metric = "val_nll"`, `goal = "min"`.
