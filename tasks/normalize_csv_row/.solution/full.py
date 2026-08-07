"""Full solution: the same cleaning, but every field converges — running it a
second time is a no-op. The percentage is only converted when the value still
looks like a percentage."""


def _as_fraction(value):
    """'15%' -> 0.15, and 0.15 -> 0.15. Already-normalised values pass through,
    which is what makes the whole row idempotent."""
    if isinstance(value, bool):
        raise ValueError(f"not a discount: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)                  # already a fraction — leave it alone
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith("%"):
        return round(float(text[:-1].strip()) / 100, 6)
    return float(text)


def normalize_row(row):
    out = dict(row)
    out["name"] = str(out.get("name", "")).strip().title()
    out["email"] = str(out.get("email", "")).strip().lower()
    out["discount"] = _as_fraction(out.get("discount", 0))
    return out
