"""Aggregate statistics with honest uncertainty — pure Python, no scipy.

When comparing two conditions across the task suite, we treat it as a **paired**
comparison (same task, two conditions) and report: the mean/median effect, a
bootstrap 95% CI, and a nonparametric **sign test** p-value. Crucially it reports
whether the result is significant *and* the power reality at the current N — so
the framework refuses to let a consistent-but-underpowered effect be overclaimed.
"""
from __future__ import annotations

import random
from math import comb


def sign_test_two_sided(n: int, k_positive: int) -> float:
    """Two-sided sign test: P(at least this lopsided) under a fair coin."""
    if n == 0:
        return 1.0
    k = max(k_positive, n - k_positive)
    tail = sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def min_n_for_significance(alpha: float = 0.05) -> int:
    """Smallest N for which an all-positive sign test reaches two-sided alpha."""
    n = 1
    while sign_test_two_sided(n, n) >= alpha and n < 100:
        n += 1
    return n


def paired_effect(diffs: list[float], boot: int = 2000, seed: int = 0) -> dict:
    if not diffs:
        return {"n": 0, "mean": 0.0, "median": 0.0, "ci95": [0.0, 0.0],
                "sign_test_p": 1.0, "significant_05": False,
                "n_positive": 0, "n_nonzero": 0, "min_n_for_sig": min_n_for_significance()}
    nonzero = [d for d in diffs if d != 0]
    n_nz = len(nonzero)
    k = sum(1 for d in nonzero if d > 0)
    mean = sum(diffs) / len(diffs)
    srt = sorted(diffs)
    median = srt[len(srt) // 2]

    rnd = random.Random(seed)
    boot_means = []
    for _ in range(boot):
        s = [diffs[rnd.randrange(len(diffs))] for _ in diffs]
        boot_means.append(sum(s) / len(s))
    boot_means.sort()
    lo = boot_means[int(0.025 * boot)]
    hi = boot_means[min(int(0.975 * boot), boot - 1)]

    p = sign_test_two_sided(n_nz, k)
    return {"n": len(diffs), "n_nonzero": n_nz, "n_positive": k,
            "mean": round(mean, 3), "median": round(median, 3),
            "ci95": [round(lo, 3), round(hi, 3)],
            "sign_test_p": round(p, 4), "significant_05": p < 0.05,
            "min_n_for_sig": min_n_for_significance()}
