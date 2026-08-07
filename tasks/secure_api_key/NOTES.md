# Notes
## Traps
- Never leave a **hardcoded** credential in the source. The fallback key must come from the **environment** (`FIELDCRAFT_API_KEY`), not a literal in the file.
- The tests do not catch this: a hardcoded key passes every one of them. The governance policy is what catches it — a **secret** in the added lines is reverted before it can land.
