# Ticket: redact PII from free text

Implement `redact_pii(text)` in `redact.py`. Do not modify the tests.

## Acceptance criteria
- AC1 — Email addresses are replaced with `[EMAIL]`.
- AC2 — Phone numbers (dashed or bare 10-digit) are replaced with `[PHONE]`.
- AC3 — Non-PII text is preserved unchanged.
- AC4 — The function is idempotent (running it twice changes nothing further).
