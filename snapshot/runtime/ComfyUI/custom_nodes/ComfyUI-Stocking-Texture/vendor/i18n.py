"""Request-local translation without the standalone application's settings files."""
import contextvars
import json
from pathlib import Path

language = contextvars.ContextVar("stocking_language", default="zh")
EN = json.loads((Path(__file__).parent / "static/i18n/en.json").read_text(encoding="utf-8"))


def tr(text, **params):
    value = EN.get(text, text) if language.get() == "en" else text
    return value.format(**params) if params else value


def both(text):
    return {text, EN.get(text, text)}
