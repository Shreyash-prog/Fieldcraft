#!/usr/bin/env python3
"""Unit checks for the measurement statistics (hand-verifiable)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fieldcraft_measure.stats import sign_test_two_sided, paired_effect, min_n_for_significance
from fieldcraft_measure.metrics import efficiency_captured, operator_quality

assert sign_test_two_sided(4, 4) == 0.125
assert sign_test_two_sided(4, 3) == 0.625
assert min_n_for_significance(0.05) == 6
pe = paired_effect([2, 1, 3, 0, -1])
assert pe["mean"] == 1.0 and pe["n_positive"] == 3 and pe["sign_test_p"] == 0.625
assert efficiency_captured(0.16, 0.08) == 0.5 and efficiency_captured(0.08, 0.08) == 1.0
assert operator_quality(1.0, 1, 2) == 0.75
print("measurement stats/metrics: all checks PASS")
