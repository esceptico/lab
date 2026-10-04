"""Do the top singular directions of the Jacobian between two layers carry the model's behaviour?

    lab run -H "..." -P "..." -- uv run --with torch --with transformers python experiment.py \
        --model gpt2 --src 4 --dst 8 --k 8
    lab run -H "..." -- modal run -m lab.modal_app --script experiment.py --args "--model gpt2-xl --src 20 --dst 30" --gpu A100-80GB

Averages J = d resid[dst] / d resid[src] (last position) over prompts, takes its right singular
vectors, projects the top k out of the residual after block `src`, and measures how much the
next-token loss on the eval texts rises. Controls: k random directions (several seeds), and
optionally the top-k SAE features at the same site (--sae-release/--sae-id, needs sae_lens).
Helpers: lab.interp.
"""

import argparse
import os
from pathlib import Path

import torch

from lab import fig, interp, log, summary

# Directions are found on PROMPTS and tested on EVAL_TEXTS: using one set for both would let the
# measurement reward overfitting to the prompts. Put your own eval set in locked/eval.txt.
DEFAULT_PROMPTS = [
    "The capital of France is",
    "She opened the door and saw",
    "In 1969, the first person to walk on the moon was",
    "The recipe calls for two cups of",
    "def fibonacci(n):\n    if n <",
    "The stock market fell sharply after",
    "My favourite season is autumn because",
    "The mitochondria is the powerhouse of",
]

DEFAULT_EVAL = [
    "The river flooded the village after three days of rain.",
    "He tuned the guitar before the concert began.",
    "Photosynthesis converts light energy into chemical energy.",
    "The committee postponed the vote until next week.",
    "import numpy as np\nx = np.zeros(10)",
    "Our train was delayed because of snow on the tracks.",
    "The painting was sold at auction for a record price.",
    "Bees communicate the location of flowers by dancing.",
]


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="gpt2")
    p.add_argument("--src", type=int, default=4)
    p.add_argument("--dst", type=int, default=8)
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--random-seeds", type=int, default=5)
    p.add_argument("--prompts", type=int, default=8, help="prompts averaged into the Jacobian")
    p.add_argument("--vectorize", action="store_true", help="faster Jacobian, more memory")
    p.add_argument("--sae-release", default=None, help='e.g. "gpt2-small-res-jb"')
    p.add_argument("--sae-id", default=None, help='e.g. "blocks.5.hook_resid_pre" (= after block 4)')
    return p.parse_args()


def texts() -> list[str]:
    """Eval texts from the campaign's locked/eval.txt (one per line) when present."""
    locked = Path(os.environ.get("LAB_LOCKED_DIR", "../../locked")) / "eval.txt"
    if locked.exists():
        return [t for t in locked.read_text().splitlines() if t.strip()]
    return DEFAULT_EVAL


def main():
    args = parse()
    model, tok = interp.load(args.model)
    prompts = DEFAULT_PROMPTS[: args.prompts]
    evals = texts()
    print(f"{args.model} on {model.device}: J({args.src}→{args.dst}) over {len(prompts)} prompts", flush=True)

    J = 0
    for i, prompt in enumerate(prompts):
        Ji = interp.jacobian(model, tok, prompt, args.src, args.dst, vectorize=args.vectorize)
        J = J + Ji / len(prompts)
        log(step=i, jacobian_norm=float(Ji.norm()))
    S, Vh = interp.spectrum(J)
    d = J.shape[0]
    if args.k >= d:
        raise SystemExit(f"--k {args.k} must be smaller than the residual width {d}")

    base = interp.next_token_loss(model, tok, evals)

    def rise(basis):
        with interp.ablate(model, args.src, basis):
            return interp.next_token_loss(model, tok, evals) - base

    jac = rise(Vh[: args.k])
    jac_mean, jac_lo, jac_hi = interp.bootstrap(jac)
    rand = torch.stack([rise(interp.random_basis(d, args.k, seed)).mean() for seed in range(args.random_seeds)])
    items = [
        {
            "label": f"Random directions (k = {args.k})",
            "mean": float(rand.mean()),
            "lo": float(rand.min()),
            "hi": float(rand.max()),
        },
        {"label": f"Jacobian top-{args.k}", "mean": jac_mean, "lo": jac_lo, "hi": jac_hi, "highlight": True},
    ]
    if args.sae_release:
        acts = torch.cat(interp.resid(model, tok, prompts, args.src))
        sae = rise(interp.sae_basis(args.sae_release, args.sae_id, acts, args.k))
        m, lo, hi = interp.bootstrap(sae)
        items.insert(1, {"label": f"SAE top-{args.k} features", "mean": m, "lo": lo, "hi": hi})

    S_norm = S / S[0]
    fig.line(
        {"J": S_norm},
        x=list(range(1, len(S_norm) + 1)),
        log_y=True,
        mark_x=(args.k + 0.5, f"top {args.k} ablated"),
        x_label="singular index",
        title=f"Singular values of J({args.src} → {args.dst})",
        sub=f"{args.model}, averaged over {len(prompts)} prompts, normalised to σ₁",
    )
    fig.dots(
        items,
        x_label="next-token loss increase",
        reference=(float(rand.mean()), "random", float(rand.std())),
        title="Loss increase when each basis is projected out",
        sub=f"after block {args.src}; CI: bootstrap over eval texts, random: min–max over seeds",
    )
    h = interp.resid(model, tok, [evals[0]], args.src)[0]
    proj = (h @ Vh[0].to(h.device)).cpu()
    words = [tok.decode([t]) for t in tok(evals[0])["input_ids"]]
    fig.tokens(
        [("eval text 1", words, proj / proj.abs().max())],
        value_label="projection (scaled)",
        title="Where the top direction is read",
        sub=f"residual after block {args.src} projected on v₁",
    )

    summary(loss_increase=jac_mean, vs_random=jac_mean - float(rand.mean()), sigma_ratio_k=float(S[args.k - 1] / S[0]))


if __name__ == "__main__":
    main()
