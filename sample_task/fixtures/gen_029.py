import re
_E = None
_P = re.compile(r'''\d{3}-\d{3}-\d{4}''')

def redact_pii(text):
    if not text:
        return text
    out = text
    if _E:
        out = _E.sub('[EMAIL]', out)
    if _P:
        out = _P.sub('[PHONE]', out)
    return out
