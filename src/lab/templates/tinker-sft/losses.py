"""Custom losses for `--loss <name>`: any differentiable function of per-token logprobs.

Tinker calls `fn(data, logprobs_list) -> (loss, metrics)`. Each `logprobs` is a torch tensor
(with grad) over the datum's target tokens; `datum.loss_fn_inputs` only carries "target_tokens"
and "weights" (floats) for custom losses, so pack anything else you need into `weights`
(tinker-cookbook's sdft.py does exactly this). Tinker backpropagates from here to the LoRA weights.
Hidden states are not available: for losses on activations, use the modal-custom template.
"""

import torch


def weighted_nll(data, logprobs_list):
    """Cross-entropy written by hand: the starting point to edit."""
    total, count = 0.0, 0.0
    for datum, logprobs in zip(data, logprobs_list, strict=True):
        weights = torch.tensor(datum.loss_fn_inputs["weights"].data, dtype=logprobs.dtype)
        total = total - torch.dot(logprobs, weights)
        count += float(weights.sum())
    loss = total / max(count, 1.0)
    return loss, {"weighted_nll": float(loss)}


def focal_nll(data, logprobs_list, gamma: float = 2.0):
    """Down-weights tokens the model already predicts well: (1 - p)^gamma * -log p."""
    total, count = 0.0, 0.0
    for datum, logprobs in zip(data, logprobs_list, strict=True):
        weights = torch.tensor(datum.loss_fn_inputs["weights"].data, dtype=logprobs.dtype)
        total = total - (((1 - logprobs.exp()) ** gamma) * logprobs * weights).sum()
        count += float(weights.sum())
    loss = total / max(count, 1.0)
    return loss, {"focal_nll": float(loss)}


CUSTOM = {"weighted_nll": weighted_nll, "focal_nll": focal_nll}
