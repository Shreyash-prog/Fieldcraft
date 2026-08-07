# Ticket: normalize_row(row)
Implement `normalize_row` in normalize_csv_row.py so all tests pass. Do not modify the tests.

A row is a dict with `name`, `email` and `discount`.

## Acceptance criteria
- NC1 — Name trimmed and title-cased.
- NC2 — Email trimmed and lower-cased.
- NC3 — Cleaning is idempotent: `normalize_row(normalize_row(row)) == normalize_row(row)`.
- NC4 — An already-normalised discount (`0.15`) is left alone, not divided again.
