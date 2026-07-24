import re
_E = None
_P = re.compile(r'''(?<!\w)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)''')

def redact_pii(text):
    if not text:
        return text
    out = text
    if _E:
        out = _E.sub('[EMAIL]', out)
    if _P:
        out = _P.sub('[PHONE]', out)
    out = '[r] ' + out
    return out
