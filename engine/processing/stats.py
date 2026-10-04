"""Honest statistics for AI-answer measurement.

AI answers vary run to run (fewer than 1 in 100 repeats return the same brand
list), so a single reading is noise. What is stable is how OFTEN the brand is
named across many answers. These helpers turn counts into a rate with a 95%
range and decide whether a change between two windows is real. Pure functions,
no DB."""

import math

Z95 = 1.959964
# Below this many answers on either side, don't call a change at all.
MIN_ANSWERS_FOR_CHANGE = 30


def wilson_interval(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials, as proportions.
    Well-behaved at small n and at 0% / 100% (unlike the normal interval)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return (lo, hi)


def two_proportion_p_value(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p-value for H0: rate1 == rate2 (pooled z-test)."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (k2 / n2 - k1 / n1) / se
    return math.erfc(abs(z) / math.sqrt(2))


def rate_summary(k: int, n: int) -> dict:
    """Rate (percent) with its 95% range and sample size."""
    lo, hi = wilson_interval(k, n)
    return {
        "rate": round(100.0 * k / n, 1) if n else 0.0,
        "low": round(100.0 * lo, 1) if n else 0.0,
        "high": round(100.0 * hi, 1) if n else 0.0,
        "answers": n,
        "mentioned": k,
    }


def change_verdict(k_before: int, n_before: int, k_after: int, n_after: int) -> dict:
    """Is the move from `before` to `after` bigger than the noise?

    'up' / 'down' only when both sides have enough answers AND the two-sided
    p-value is below 0.05; otherwise 'no real change' or 'not enough data'."""
    if n_before < MIN_ANSWERS_FOR_CHANGE or n_after < MIN_ANSWERS_FOR_CHANGE:
        return {"verdict": "not enough data", "delta": None, "p_value": None}
    delta = round(100.0 * (k_after / n_after - k_before / n_before), 1)
    p = two_proportion_p_value(k_before, n_before, k_after, n_after)
    if p < 0.05:
        verdict = "up" if delta > 0 else "down"
    else:
        verdict = "no real change"
    return {"verdict": verdict, "delta": delta, "p_value": round(p, 4)}


Z_POWER80 = 0.8416  # one-sided z for 80% power


def answers_needed(
    p: float, delta: float, *, z_alpha: float = Z95, z_beta: float = Z_POWER80
) -> int:
    """Answers needed on EACH side of a before/after comparison to detect a
    change of `delta` (as a fraction, e.g. 0.10) from baseline rate `p` with
    a two-sided 5% test at 80% power (two-proportion formula). Clamped to
    [MIN_ANSWERS_FOR_CHANGE, 100000]."""
    p1 = min(max(p, 0.01), 0.99)
    p2 = min(max(p1 + delta, 0.01), 0.99)
    if p2 == p1:
        return 100_000
    pbar = (p1 + p2) / 2
    num = (z_alpha * math.sqrt(2 * pbar * (1 - pbar))
           + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    n = math.ceil(num / (p2 - p1) ** 2)
    return max(MIN_ANSWERS_FOR_CHANGE, min(n, 100_000))


def detectable_change(p: float, n_per_side: int) -> float | None:
    """Smallest change (percentage points) detectable with n answers per side
    at 80% power, or None when there's too little data to say."""
    if n_per_side < MIN_ANSWERS_FOR_CHANGE:
        return None
    for pts in range(1, 101):
        if answers_needed(p, pts / 100) <= n_per_side:
            return float(pts)
    return None
