from __future__ import annotations

from quizhub.textutil import normalize

# Если все фрагменты есть в названии, квизу ставится тег.
# Так «Игра престолов» находится по слову «сериалы», а «кино + музыка» — по «ким».
TAG_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("игра престолов",), "сериалы"),
    (("гарри поттер",), "гарри поттер"),
    (("кино", "музыка"), "ким"),
    (("рок",), "рок"),
    (("аниме",), "аниме"),
    (("караоке",), "караоке"),
    (("литератур",), "литература"),
    (("классика",), "классика"),
    (("нович",), "новички"),
    (("мелод",), "музыка"),
    (("хит",), "музыка"),
)


def infer_tags(*parts: str) -> list[str]:
    blob = normalize(" ".join(parts))
    found: list[str] = []
    for needles, tag in TAG_RULES:
        if all(needle in blob for needle in needles) and tag not in found:
            found.append(tag)
    return found


def merge_tags(explicit: list[str], *parts: str) -> list[str]:
    result: list[str] = []
    for tag in [*explicit, *infer_tags(*parts)]:
        clean = normalize(tag)
        if clean and clean not in result:
            result.append(clean)
    return result
