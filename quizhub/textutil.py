from __future__ import annotations

import re

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(value: str) -> str:
    text = value.lower().replace("ё", "е")
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def plural_quizzes(count: int) -> str:
    number = abs(count) % 100
    tail = number % 10
    if 11 <= number <= 19:
        return "квизов"
    if tail == 1:
        return "квиз"
    if 2 <= tail <= 4:
        return "квиза"
    return "квизов"
