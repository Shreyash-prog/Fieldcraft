import re
_E = None
_P = None

def redact_pii(text):
    if not text:
        return text
    out = text
    if _E:
        out = _E.sub('[EMAIL]', out)
    if _P:
        out = _P.sub('[PHONE]', out)
    out = out.upper()
    return out
