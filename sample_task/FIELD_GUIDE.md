# Field Guide — sample_task
`commit: unpinned`

## Test strategy
1 test file(s), pytest-style. Run tests before declaring a task done.

## House conventions
- Type hints on ~12% of top-level functions (1/8)
- Docstrings on ~12% of top-level functions

## Traps & notes
- Phone numbers appear in both dashed (415-555-2671) and bare (4155552671) formats — redact_pii must handle both.
- Redaction must be idempotent: running it twice must not change the result further.

## Glossary
- **redact_pii** — core symbol
- **test_masks_email** — core symbol
- **test_masks_phone** — core symbol
- **test_masks_bare_phone** — core symbol
- **test_preserves_plain_text** — core symbol
- **test_multiple_and_mixed** — core symbol
- **test_idempotent** — core symbol
- **test_empty** — core symbol

## Module map
- `redact.py` (module) · redact_pii
- `test_redact.py` (test) · test_masks_email, test_masks_phone, test_masks_bare_phone, test_preserves_plain_text, test_multiple_and_mixed, test_idempotent, test_empty
