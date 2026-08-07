from normalize_csv_row import normalize_row

RAW = {"name": "  ada lovelace ", "email": " ADA@Example.COM ", "discount": "15%"}


def test_trims_and_titlecases_the_name():
    assert normalize_row(RAW)["name"] == "Ada Lovelace"


def test_lowercases_the_email():
    assert normalize_row(RAW)["email"] == "ada@example.com"


def test_converts_a_percentage_to_a_fraction():
    assert normalize_row(RAW)["discount"] == 0.15


def test_is_idempotent():
    """The catch. Cleaning an already-clean row must change nothing — a pipeline
    re-run must not silently corrupt rows it already processed."""
    once = normalize_row(RAW)
    twice = normalize_row(once)
    assert twice == once


def test_an_already_normalised_discount_is_left_alone():
    """The specific failure: 0.15 must stay 0.15, not become 0.0015."""
    assert normalize_row({"name": "Ada", "email": "a@b.co", "discount": 0.15})["discount"] == 0.15


def test_handles_a_missing_discount():
    assert normalize_row({"name": "Ada", "email": "a@b.co"})["discount"] == 0.0
