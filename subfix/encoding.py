"""Определение кодировки: старые русские субтитры почти всегда в Windows-1251."""

import codecs

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_FALLBACKS = ("cp1251", "koi8-r", "cp1252")


def _cyrillic_score(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    # Частые строчные буквы русского текста: у верной кодировки их много,
    # у ошибочной (например, koi8-r вместо cp1251) много заглавных и редких букв.
    common = set("оеаинтсрвлкмдпуяыьгзбчйхжшюцщэфъё")
    good = sum(1 for ch in letters if ch in common)
    return good / len(letters)


def detect(data: bytes) -> str:
    for bom, name in _BOMS:
        if data.startswith(bom):
            return name
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    best, best_score = "cp1252", 0.5
    for name in _FALLBACKS[:2]:
        try:
            score = _cyrillic_score(data.decode(name))
        except UnicodeDecodeError:
            continue
        if score > best_score:
            best, best_score = name, score
    return best


def decode(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    """Возвращает (текст, использованная кодировка)."""
    name = encoding or detect(data)
    try:
        return data.decode(name), name
    except (UnicodeDecodeError, LookupError) as exc:
        raise ValueError(f"не удалось прочитать файл в кодировке {name}: {exc}") from None
