# Notes
## Traps
- `normalize_row` must be **idempotent**: running it twice must equal running it once, because pipelines re-run rows on retries and backfills.
- The percentage field is the one that breaks. Converting `"15%"` to `0.15` unconditionally means a second pass turns `0.15` into `0.0015`. Only convert a value that still looks like a percentage; leave an already-normalised number alone.
- Trimming and title-casing are already idempotent — the discount conversion is the only step that needs the guard.
