from redact import redact_pii


def test_masks_email():
    assert redact_pii("reach me at ada@example.com") == "reach me at [EMAIL]"


def test_masks_phone():
    assert redact_pii("call 415-555-2671 today") == "call [PHONE] today"


def test_masks_bare_phone():
    assert redact_pii("num 4155552671") == "num [PHONE]"


def test_preserves_plain_text():
    assert redact_pii("hello world, nothing to see") == "hello world, nothing to see"


def test_multiple_and_mixed():
    out = redact_pii("x@y.com or 4155552671")
    assert "[EMAIL]" in out and "[PHONE]" in out and "@" not in out


def test_idempotent():
    once = redact_pii("ada@example.com 415-555-2671")
    assert redact_pii(once) == once


def test_empty():
    assert redact_pii("") == ""
