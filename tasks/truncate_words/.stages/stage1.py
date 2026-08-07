"""Turn-1 attempt: budgets characters instead of words and always appends the
ellipsis. Looks right on a long sentence; cuts mid-word, and marks short text as
truncated when nothing was removed."""


def truncate_words(text, limit):
    budget = limit * 6                       # "about six characters per word"
    return (text or "")[:budget].strip() + "…"
