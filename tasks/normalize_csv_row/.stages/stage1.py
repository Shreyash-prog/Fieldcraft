"""Turn-1 attempt: does the obvious cleaning, and converts the percentage every
single time it is called. Correct on a fresh row, wrong the moment the row is
processed twice — which is what a pipeline re-run does."""


def normalize_row(row):
    out = dict(row)
    out["name"] = str(out.get("name", "")).strip().title()
    out["email"] = str(out.get("email", "")).strip().lower()
    # Unconditional: strips a '%' that may not be there and divides regardless.
    out["discount"] = float(str(out.get("discount", "0")).replace("%", "").strip()) / 100
    return out
