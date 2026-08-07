# Notes
## Traps
- Break on a word **boundary**, never mid-word. Budgeting characters ("about six per word") looks right on a long sentence and produces `checkpoi…` on a short one.
- The **ellipsis** is a signal that something was removed. If the text was already within the limit, return it unchanged — no ellipsis.
- Text exactly at the limit counts as not truncated.
