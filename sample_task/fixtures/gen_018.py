import re
_E = re.compile(r'''\S+@\S+\.\S+''')
_P = re.compile(r'''\d{3}-\d{3}-\d{4}''')

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
