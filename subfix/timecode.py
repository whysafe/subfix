"""Разбор и форматирование таймкодов. Внутри всё хранится в миллисекундах."""

import re

_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")
_UNITS = re.compile(r"^(\d+(?:[.,]\d+)?)(ms|s|m|h)?$")
_UNIT_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000, None: 1000}


class TimecodeError(ValueError):
    """Строку нельзя прочитать как время."""


def parse_clock(text: str) -> int:
    """'01:02:03,456', '02:03.456' или '1:02:03' -> миллисекунды."""
    match = _CLOCK.match(text.strip())
    if not match:
        raise TimecodeError(f"не похоже на таймкод: {text!r}")
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) > 59 or int(seconds) > 59:
        raise TimecodeError(f"минуты и секунды должны быть меньше 60: {text!r}")
    ms = int((fraction or "0").ljust(3, "0"))
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + ms


def parse_offset(text: str) -> int:
    """Сдвиг со знаком: '+1.5', '-2s', '500ms', '-00:00:01,200' -> миллисекунды."""
    raw = text.strip().replace(" ", "").replace("−", "-")
    if not raw:
        raise TimecodeError("пустой сдвиг")
    sign = -1 if raw[0] == "-" else 1
    body = raw[1:] if raw[0] in "+-" else raw
    if ":" in body:
        return sign * parse_clock(body)
    match = _UNITS.match(body.lower())
    if not match:
        raise TimecodeError(f"не понимаю сдвиг: {text!r} (примеры: 2.5, -1500ms, +00:00:03,000)")
    value, unit = match.groups()
    return sign * round(float(value.replace(",", ".")) * _UNIT_MS[unit])


def format_srt(ms: int) -> str:
    ms = max(0, int(ms))
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_vtt(ms: int) -> str:
    return format_srt(ms).replace(",", ".")


def format_human(ms: int) -> str:
    """Короткая запись для отчётов: '1:02:03.4' или '-0:01.5'."""
    sign = "-" if ms < 0 else ""
    ms = abs(int(ms))
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds = rest / 1000
    if hours:
        return f"{sign}{hours}:{minutes:02d}:{seconds:04.1f}"
    return f"{sign}{minutes}:{seconds:04.1f}"
