import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact_pii(text: str) -> str:
    if not text:
        return text
    return _EMAIL.sub("[EMAIL]", text)
