"""Calibration numbers shared by lab.fig and lab bench. Standard library only."""


def reliability_bins(confidence: list[float], correct: list[float], bins: int = 10) -> tuple[list[dict], float]:
    """Equal-width confidence bins ({conf, acc, n} for non-empty ones) and the expected calibration error."""
    if any(not 0 <= c <= 1 for c in confidence):  # also catches NaN
        raise ValueError("confidence values must be probabilities in [0, 1]")
    groups: list[list[int]] = [[] for _ in range(bins)]
    for i, c in enumerate(confidence):
        groups[min(int(c * bins), bins - 1)].append(i)
    out, ece = [], 0.0
    for b, idx in enumerate(groups):
        if not idx:
            continue
        mean_conf = sum(confidence[i] for i in idx) / len(idx)
        acc = sum(float(correct[i]) for i in idx) / len(idx)
        ece += len(idx) / len(confidence) * abs(acc - mean_conf)
        out.append({"conf": (b + 0.5) / bins, "acc": acc, "n": len(idx)})
    return out, ece


def brier(probabilities: list[list[float]], gold: list[int]) -> float:
    """Mean over items of the squared distance between the predicted distribution and the one-hot answer."""
    total = sum(
        sum((p - (i == g)) ** 2 for i, p in enumerate(probs)) for probs, g in zip(probabilities, gold, strict=True)
    )
    return total / len(gold) if gold else float("nan")
