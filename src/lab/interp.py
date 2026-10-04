"""Interpretability helpers for Hugging Face causal LMs. Needs torch and transformers (run-side only).

Residual stream convention: `layer` L means the output of block L (the residual after it).
Everything is plain torch with forward hooks; no TransformerLens or nnsight needed.
"""

import contextlib
from collections.abc import Callable, Iterator, Sequence

import torch
from torch import nn


def load(name: str, device: str | None = None, dtype: torch.dtype | None = None):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(name)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(name, dtype=dtype or torch.float32).to(device).eval()
    for p in model.parameters():
        p.requires_grad_(False)
    return model, tok


def blocks(model: nn.Module) -> nn.ModuleList:
    """The decoder layers: the module list as long as the config's layer count, all of one block class."""
    n = model.config.get_text_config().num_hidden_layers
    for module in model.modules():
        if isinstance(module, nn.ModuleList) and len(module) == n and len({type(m) for m in module}) == 1:
            return module
    raise ValueError(f"no list of {n} identical blocks in {type(model).__name__}")


def _hidden(out):
    return out[0] if isinstance(out, tuple) else out


def _replace(out, hidden):
    return (hidden, *out[1:]) if isinstance(out, tuple) else hidden


@torch.no_grad()
def resid(model, tok, texts: Sequence[str], layer: int) -> list[torch.Tensor]:
    """Residual after block `layer` for each text: a list of [seq, d] tensors (no padding).

    Read with a hook on the block output, not `hidden_states`: HF applies the final norm to the
    last entry of `hidden_states` (GPT-2's ln_f), which is not the raw residual.
    """
    out, captured = [], {}
    handle = blocks(model)[layer].register_forward_hook(lambda _, __, o: captured.__setitem__("h", _hidden(o)))
    try:
        for text in texts:
            model(**tok(text, return_tensors="pt").to(model.device))
            out.append(captured["h"][0].float())
    finally:
        handle.remove()
    return out


def jacobian(model, tok, text: str, src: int, dst: int, pos: int = -1, vectorize: bool = False) -> torch.Tensor:
    """d resid[dst][pos] / d resid[src][pos] for one text: a [d, d] matrix.

    The residual at `pos` after block `src` is replaced by a free variable; everything else in
    the forward pass is fixed. `vectorize=True` is faster but needs more memory.
    """
    ids = tok(text, return_tensors="pt").to(model.device)
    layers = blocks(model)
    base = resid(model, tok, [text], src)[0][pos]

    def f(h: torch.Tensor) -> torch.Tensor:
        captured = {}

        def put(_, __, out):
            new = _hidden(out).clone()
            new[:, pos] = h.to(new.dtype)
            return _replace(out, new)

        def take(_, __, out):
            captured["h"] = _hidden(out)[0, pos]

        handles = [layers[src].register_forward_hook(put), layers[dst].register_forward_hook(take)]
        try:
            model(**ids)
        finally:
            for handle in handles:
                handle.remove()
        return captured["h"].float()

    return torch.autograd.functional.jacobian(f, base, vectorize=vectorize)


def spectrum(J: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Singular values and right singular vectors (rows, in the source residual space)."""
    _, S, Vh = torch.linalg.svd(J.float().cpu(), full_matrices=False)  # MPS falls back to CPU anyway
    return S, Vh


def random_basis(d: int, k: int, seed: int) -> torch.Tensor:
    g = torch.Generator().manual_seed(seed)
    q, _ = torch.linalg.qr(torch.randn(d, k, generator=g))
    return q.T  # [k, d], orthonormal rows


@contextlib.contextmanager
def ablate(model, layer: int, basis: torch.Tensor, position: int | None = None) -> Iterator[None]:
    """Project the span of `basis` ([k, d], any rows) out of the residual after block `layer`.

    `position=None` ablates every position. A Jacobian taken at one position describes that
    position; pass the same `position` to test exactly what it measured.
    """
    q, _ = torch.linalg.qr(basis.float().T)  # orthonormalise: [d, k]
    q = q.to(next(model.parameters()).device)

    def hook(_, __, out):
        hs = _hidden(out)
        h = hs.float()
        removed = h - (h @ q) @ q.T
        if position is not None:
            kept = h.clone()
            kept[:, position] = removed[:, position]
            removed = kept
        return _replace(out, removed.to(hs.dtype))

    handle = blocks(model)[layer].register_forward_hook(hook)
    try:
        yield
    finally:
        handle.remove()


@torch.no_grad()
def next_token_loss(model, tok, texts: Sequence[str]) -> torch.Tensor:
    """Mean next-token loss per text: a [n] tensor (bootstrap over it for intervals)."""
    losses = []
    for text in texts:
        ids = tok(text, return_tensors="pt").to(model.device)
        losses.append(model(**ids, labels=ids["input_ids"]).loss.float().cpu())
    return torch.stack(losses)


def sae_basis(release: str, sae_id: str, acts: torch.Tensor, k: int) -> torch.Tensor:
    """Decoder directions of the k SAE features most active on `acts` ([n, d]). Needs sae_lens."""
    from sae_lens import SAE

    loaded = SAE.from_pretrained(release, sae_id)
    sae = loaded[0] if isinstance(loaded, tuple) else loaded  # sae_lens < 6 returned a tuple
    feats = sae.encode(acts.to(sae.W_dec.device, sae.W_dec.dtype))
    top = feats.mean(0).topk(k).indices
    return sae.W_dec[top].float().cpu()


def bootstrap(
    values: torch.Tensor, stat: Callable[[torch.Tensor], torch.Tensor] = torch.mean, n: int = 1000, seed: int = 0
):
    """(statistic, low, high): the statistic over `values` and its 95% percentile bootstrap interval."""
    g = torch.Generator().manual_seed(seed)
    idx = torch.randint(0, len(values), (n, len(values)), generator=g)
    stats = torch.stack([stat(values[i]) for i in idx])
    return float(stat(values)), float(stats.quantile(0.025)), float(stats.quantile(0.975))
