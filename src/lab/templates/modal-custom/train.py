"""Any PyTorch training, locally or on a Modal GPU. Edit freely: this is the file experiments change.

    lab run -H "..." -- python train.py --lr 3e-3                                  # local
    lab run -H "..." -- modal run -m lab.modal_app --script train.py --args "--lr 3e-3" --gpu A10

The example trains a small MLP on a synthetic task with a hidden-state penalty in the loss:
the kind of loss Tinker cannot express, because it needs activations. Replace model, data and
loss with yours; keep `log`, `summary` and `fig` calls so runs stay comparable.
Checkpoints go to $LAB_DATA_DIR when the runner provides one (Modal: the `lab-data` volume), not to artifacts.
"""

import argparse
import os

import torch
from torch import nn

from lab import fig, log, summary


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--lr", type=float, default=3e-3)
    p.add_argument("--steps", type=positive, default=600)
    p.add_argument("--width", type=int, default=128)
    p.add_argument("--sparsity", type=float, default=1e-3, help="L1 weight on hidden activations")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def data(n: int, gen: torch.Generator, device: str):
    x = torch.randn(n, 16, generator=gen)
    y = (torch.sin(x[:, :4].sum(1)) + 0.3 * x[:, 4] * x[:, 5] > 0).long()
    return x.to(device), y.to(device)


class Net(nn.Module):
    def __init__(self, width: int):
        super().__init__()
        self.inp = nn.Linear(16, width)
        self.out = nn.Linear(width, 2)

    def forward(self, x):
        h = torch.relu(self.inp(x))
        return self.out(h), h


def main():
    args = parse()
    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    gen = torch.Generator().manual_seed(args.seed)
    torch.manual_seed(args.seed)
    xtr, ytr = data(8192, gen, device)
    xva, yva = data(2048, gen, device)
    model = Net(args.width).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    print(f"device {device}", flush=True)

    for step in range(args.steps):
        idx = torch.randint(0, len(xtr), (256,), generator=gen).to(device)
        logits, h = model(xtr[idx])
        task = nn.functional.cross_entropy(logits, ytr[idx])
        loss = task + args.sparsity * h.abs().mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        if step % 20 == 0 or step == args.steps - 1:
            with torch.no_grad():
                vlogits, vh = model(xva)
                val_loss = nn.functional.cross_entropy(vlogits, yva).item()
                val_acc = (vlogits.argmax(1) == yva).float().mean().item()
            log(step=step, loss=task.item(), val_loss=val_loss, val_acc=val_acc, active=(vh > 0).float().mean().item())

    usage = (vh > 0).float().mean(0).sort(descending=True).values.cpu()  # vh: the last step's validation pass
    fig.line(
        {"fraction active": usage},
        x=list(range(1, len(usage) + 1)),
        x_label="hidden unit (sorted)",
        title="Hidden-unit usage",
        caption=f"L1 weight {args.sparsity}: share of validation inputs on which each unit fires.",
    )
    if checkpoints := os.environ.get("LAB_DATA_DIR"):
        torch.save(model.state_dict(), f"{checkpoints}/{os.environ.get('LAB_RUN_ID', 'run')}.pt")
    summary(val_loss=val_loss, val_acc=val_acc)


if __name__ == "__main__":
    main()
