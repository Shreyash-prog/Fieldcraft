"""Full solution: counts words, never splits one, and only signals truncation
when something was actually removed."""


def truncate_words(text, limit):
    words = (text or "").split()
    if limit <= 0:
        return "…" if words else ""
    if len(words) <= limit:
        return " ".join(words)               # nothing removed -> no ellipsis
    return " ".join(words[:limit]) + "…"
