import re
_P = re.compile(r"(?<!\w)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")
def redact_pii(text: str) -> str:
    return text if not text else _P.sub("[PHONE]", text)
