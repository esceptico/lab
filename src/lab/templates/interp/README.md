# interp

A Jacobian-subspace experiment on any Hugging Face causal LM, with controls built in.

- `experiment.py`: averages J = ∂resid[dst]/∂resid[src] over prompts, takes its right singular
  vectors, projects the top k out after block `src`, and measures the rise in next-token loss.
  Controls: k random directions over several seeds; optionally the top-k SAE features at the
  same site. Figures: the singular spectrum, a dot plot of the three bases, and a token strip of
  where the top direction is read. Summary: `loss_increase`, `vs_random`, `sigma_ratio_k`.
- The helpers are in `lab.interp` (`from lab import interp`): `load`, `blocks`, `resid`, `jacobian`,
  `spectrum`, `random_basis`, `ablate`, `next_token_loss`, `sae_basis`, `bootstrap`. They are plain
  torch plus hooks, and work across GPT-2, Llama, Qwen, Gemma and NeoX block layouts.

Eval texts: `locked/eval.txt` (one per line), so the measurement is hashed; otherwise built-in prompts.

```bash
lab run -H "Top-8 J(4→8) directions matter more than random" -P "vs_random > 0.1" -- \
  uv run --with torch --with transformers python experiment.py --model gpt2 --src 4 --dst 8 --k 8
lab run -H "..." -- modal run -m lab.modal_app --script experiment.py \
  --args "--model Qwen/Qwen3-8B --src 14 --dst 24" --gpu A100-80GB
```
Set the campaign `metric = "vs_random"`, `goal = "max"`. On large models use `--vectorize` on a
GPU with memory to spare; each prompt costs one forward pass plus d backward passes.
