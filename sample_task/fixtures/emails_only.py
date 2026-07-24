import re
_E = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
def redact_pii(text: str) -> str:
    return text if not text else _E.sub("[EMAIL]", text)
