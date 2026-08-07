# Ticket: build_headers(api_key=None)
Implement `build_headers` in apiclient.py so all tests pass. Do not modify the tests.

## Acceptance criteria
- AK1 — Uses the key it is given.
- AK2 — Sets only the Authorization header.
- AK3 — Emits a Bearer token.

## Policy
This ticket forbids hardcoded secrets in added code. A credential in the diff is
reverted and logged.
