"""Supervised fine-tuning on Tinker, with an optional custom loss.

    lab run -H "..." -P "..." -- uv run --with tinker --with tinker-cookbook python train.py \
        --model Qwen/Qwen3-8B --lr 1e-4

Data: JSONL, one {"messages": [{"role": ..., "content": ...}, ...]} per line (chat format); by default
train.jsonl and val.jsonl in the campaign's locked/ ($LAB_LOCKED_DIR), so the data is hashed.
Needs TINKER_API_KEY. Follows tinker-cookbook's recipes/sl_loop.py (checked 2026-09-23).
"""

import argparse
import json
import os
import random
import time

import losses
import tinker
from tinker_cookbook import model_info, renderers
from tinker_cookbook.supervised.common import compute_mean_nll
from tinker_cookbook.supervised.data import conversation_to_datum
from tinker_cookbook.tokenizer_utils import get_tokenizer

from lab import log, summary


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    locked = os.environ.get("LAB_LOCKED_DIR", "locked")
    p.add_argument("--data", default=f"{locked}/train.jsonl")
    p.add_argument("--val", default=f"{locked}/val.jsonl")
    p.add_argument("--model", default="Qwen/Qwen3-8B")
    p.add_argument("--rank", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--max-length", type=int, default=4096)
    p.add_argument("--eval-every", type=int, default=20)
    p.add_argument("--loss", choices=["cross_entropy", *losses.CUSTOM], default="cross_entropy")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def load(path: str) -> list[list[dict]]:
    with open(path) as f:
        return [json.loads(line)["messages"] for line in f if line.strip()]


def mean_nll(result, batch) -> float:
    logprobs = [x["logprobs"] for x in result.loss_fn_outputs]
    return compute_mean_nll(logprobs, [d.loss_fn_inputs["weights"] for d in batch])


def train(args, client, to_datum, train_rows, val_rows) -> float:
    rng = random.Random(args.seed)
    val = [to_datum(m) for m in val_rows]
    steps_per_epoch = len(train_rows) // args.batch
    if steps_per_epoch == 0:
        raise SystemExit(f"need at least --batch ({args.batch}) training rows, got {len(train_rows)}")
    total = steps_per_epoch * args.epochs
    if args.max_steps is not None:
        total = min(total, args.max_steps)
    tokens, val_nll = 0, float("nan")
    for step in range(total):
        b = step % steps_per_epoch
        if b == 0:  # a new epoch, in a new order
            order = list(range(len(train_rows)))
            rng.shuffle(order)
        started = time.time()
        batch = [to_datum(train_rows[i]) for i in order[b * args.batch : (b + 1) * args.batch]]
        lr = args.lr * max(0.0, 1.0 - step / total)  # linear decay, as in the cookbook
        if args.loss == "cross_entropy":
            fb = client.forward_backward(batch, loss_fn="cross_entropy")
        else:
            fb = client.forward_backward_custom(batch, losses.CUSTOM[args.loss])
        opt = client.optim_step(tinker.AdamParams(learning_rate=lr, beta1=0.9, beta2=0.95, eps=1e-8))
        result = fb.result()
        opt.result()
        tokens += sum(d.model_input.length for d in batch)
        point = {"train_nll": mean_nll(result, batch), "lr": lr, "tokens": tokens, "sec": time.time() - started}
        point.update({f"loss/{k}": v for k, v in (result.metrics or {}).items()})
        if step % args.eval_every == 0 or step == total - 1:
            val_nll = mean_nll(client.forward(val, loss_fn="cross_entropy").result(), val)
            point["val_nll"] = val_nll
        log(step=step, **point)
    return val_nll


def main() -> None:
    args = parse()
    tokenizer = get_tokenizer(args.model)
    renderer = renderers.get_renderer(model_info.get_recommended_renderer_name(args.model), tokenizer)

    def to_datum(messages):
        return conversation_to_datum(messages, renderer, args.max_length, renderers.TrainOnWhat.ALL_ASSISTANT_MESSAGES)

    client = tinker.ServiceClient().create_lora_training_client(base_model=args.model, rank=args.rank, seed=args.seed)
    val_nll = train(args, client, to_datum, load(args.data), load(args.val))
    sampler = client.save_weights_for_sampler(name="final").result()
    print("weights:", sampler.path)
    summary(val_nll=val_nll)


if __name__ == "__main__":
    main()
