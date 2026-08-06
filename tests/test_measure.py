"""Measurement stats + metrics — hand-verifiable numbers (no mocks, fully real)."""
from fieldcraft_measure.stats import sign_test_two_sided, paired_effect, min_n_for_significance
from fieldcraft_measure.metrics import (efficiency_captured, operator_quality,
                                        composite_effectiveness, Scorecard)


def test_sign_test_known_values():
    assert sign_test_two_sided(4, 4) == 0.125
    assert sign_test_two_sided(4, 3) == 0.625
    assert abs(sign_test_two_sided(6, 6) - 0.03125) < 1e-9
    assert sign_test_two_sided(0, 0) == 1.0

def test_min_n_for_significance():
    assert min_n_for_significance(0.05) == 6

def test_paired_effect_hand_checked():
    pe = paired_effect([2, 1, 3, 0, -1])
    assert pe["mean"] == 1.0
    assert pe["n_nonzero"] == 4 and pe["n_positive"] == 3
    assert pe["sign_test_p"] == 0.625

def test_paired_effect_empty():
    pe = paired_effect([])
    assert pe["n"] == 0 and pe["sign_test_p"] == 1.0

def test_efficiency_captured():
    assert efficiency_captured(0.16, 0.08) == 0.5
    assert efficiency_captured(0.08, 0.08) == 1.0
    assert efficiency_captured(0.0, 0.08) == 1.0          # zero-cost guard

def test_operator_quality_discounts_rework():
    assert operator_quality(1.0, 0, 2) == 1.0
    assert operator_quality(1.0, 1, 2) == 0.75

def test_composite_effectiveness_and_validity():
    score, valid = composite_effectiveness(1.0, 1.0, integrity_ok=True)
    assert score == 1.0 and valid is True
    score, valid = composite_effectiveness(1.0, 0.0, integrity_ok=False)
    assert valid is False                                  # integrity gate

def test_scorecard_build():
    sc = Scorecard.build("t", "blind", test_rate=1.0, criteria_rate=1.0, integrity_ok=True,
                         actual_cost=0.16, reference_cost=0.08, iterations=2, rework=0)
    assert sc.efficiency_captured == 0.5 and sc.valid is True
