"""Local message formatting adapter, without desktop settings or global language state."""


def tr(text, **params):
    return text.format(**params) if params else text
