from truncate_words import truncate_words

SENTENCE = "the quick brown fox jumps over the lazy dog"


def test_truncates_to_the_word_limit():
    assert truncate_words(SENTENCE, 4) == "the quick brown fox…"


def test_never_cuts_mid_word():
    """The catch, part one. Every word in the output must be a whole word."""
    out = truncate_words(SENTENCE, 3).rstrip("…")
    assert all(w in SENTENCE.split() for w in out.split())


def test_no_ellipsis_when_nothing_was_removed():
    """The catch, part two. Short text comes back untouched."""
    assert truncate_words("two words", 5) == "two words"


def test_exactly_at_the_limit_is_not_truncated():
    assert truncate_words("one two three", 3) == "one two three"


def test_empty_text():
    assert truncate_words("", 3) == ""
