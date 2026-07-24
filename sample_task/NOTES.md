# Notes

## Traps
- Phone numbers appear in both dashed (415-555-2671) and bare (4155552671) formats — redact_pii must handle both.
- Redaction must be idempotent: running it twice must not change the result further.
