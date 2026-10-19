"""Операции над списком субтитров. Каждая функция возвращает новый список."""

import re
from dataclasses import dataclass, replace

from .formats import Cue

_TAGS = re.compile(r"</?[a-zA-Z][^>]*>|\{\\[^}]*\}")
_SDH = re.compile(r"\[[^\]]*\]|\([^)]*\)|[♪♫]+")
_SPEAKER = re.compile(r"^[A-ZА-ЯЁ][A-ZА-ЯЁ0-9 .'-]{1,30}:\s*")
_DASH_ONLY = re.compile(r"^[-–—\s]*$")


def shift(cues: list[Cue], offset_ms: int, after_ms: int = 0) -> list[Cue]:
    """Сдвигает субтитры, начинающиеся не раньше after_ms. Время не уходит ниже нуля."""
    result = []
    for cue in cues:
        if cue.start >= after_ms:
            cue = replace(cue, start=max(0, cue.start + offset_ms), end=max(0, cue.end + offset_ms))
        result.append(cue)
    return result


def linear(cues: list[Cue], scale: float, offset_ms: float = 0.0) -> list[Cue]:
    """t' = t * scale + offset."""
    if scale <= 0:
        raise ValueError("масштаб времени должен быть положительным")
    return [
        replace(c, start=max(0, round(c.start * scale + offset_ms)), end=max(0, round(c.end * scale + offset_ms)))
        for c in cues
    ]


def change_fps(cues: list[Cue], source_fps: float, target_fps: float) -> list[Cue]:
    """Пересчёт под другую частоту кадров, например 23.976 -> 25 для PAL-рипов."""
    if source_fps <= 0 or target_fps <= 0:
        raise ValueError("частота кадров должна быть положительной")
    return linear(cues, source_fps / target_fps)


@dataclass(frozen=True)
class SyncPoint:
    current_ms: int
    correct_ms: int


def two_point_sync(cues: list[Cue], first: SyncPoint, second: SyncPoint) -> tuple[list[Cue], float, float]:
    """Растягивает и сдвигает так, чтобы две опорные точки встали на место.

    Помогает, когда субтитры в начале фильма отстают на 1 секунду, а в конце на 4:
    обычный сдвиг тут не справится, нужен ещё и масштаб.
    """
    span = second.current_ms - first.current_ms
    if span == 0:
        raise ValueError("опорные точки должны быть в разных местах фильма")
    scale = (second.correct_ms - first.correct_ms) / span
    if scale <= 0:
        raise ValueError("опорные точки идут в обратном порядке")
    offset = first.correct_ms - first.current_ms * scale
    return linear(cues, scale, offset), scale, offset


def strip_tags(cues: list[Cue]) -> list[Cue]:
    """Убирает <i>, <font color=...>, {\\an8} и подобную разметку."""
    return [replace(c, text=_TAGS.sub("", c.text)) for c in cues]


def strip_sdh(cues: list[Cue]) -> list[Cue]:
    """Убирает пометки для слабослышащих: [смех], (дверь хлопает), ♪, «ДЖОН:»."""
    result = []
    for cue in cues:
        lines = []
        for line in cue.text.split("\n"):
            line = _SPEAKER.sub("", _SDH.sub("", line)).strip()
            line = re.sub(r"\s{2,}", " ", line)
            if line and not _DASH_ONLY.match(line):
                lines.append(line)
        result.append(replace(cue, text="\n".join(lines)))
    return result


def drop_empty(cues: list[Cue]) -> list[Cue]:
    return [c for c in cues if c.text.strip()]


def sort_cues(cues: list[Cue]) -> list[Cue]:
    return sorted(cues, key=lambda c: (c.start, c.end))


def fix_overlaps(cues: list[Cue], gap_ms: int = 1) -> tuple[list[Cue], int]:
    """Обрезает конец субтитра, если он налезает на следующий. Возвращает (список, число правок)."""
    result = sort_cues(cues)
    fixed = 0
    for i in range(len(result) - 1):
        current, following = result[i], result[i + 1]
        limit = following.start - gap_ms
        if current.end > limit:
            result[i] = replace(current, end=max(current.start, limit))
            fixed += 1
    return result, fixed


def extend_short(cues: list[Cue], min_ms: int, gap_ms: int = 1) -> tuple[list[Cue], int]:
    """Удлиняет слишком короткие субтитры, но не залезая на следующий."""
    result = sort_cues(cues)
    fixed = 0
    for i, cue in enumerate(result):
        if cue.duration >= min_ms:
            continue
        end = cue.start + min_ms
        if i + 1 < len(result):
            end = min(end, result[i + 1].start - gap_ms)
        if end > cue.end:
            result[i] = replace(cue, end=end)
            fixed += 1
    return result, fixed


@dataclass
class Report:
    count: int
    first_ms: int
    last_ms: int
    overlaps: int
    too_short: int
    long_lines: int
    unsorted: int
    empty: int
    with_tags: int


def analyze(cues: list[Cue], max_line: int = 42, min_ms: int = 700) -> Report:
    overlaps = sum(1 for a, b in zip(cues, cues[1:]) if a.end > b.start)
    unsorted = sum(1 for a, b in zip(cues, cues[1:]) if b.start < a.start)
    return Report(
        count=len(cues),
        first_ms=min(c.start for c in cues),
        last_ms=max(c.end for c in cues),
        overlaps=overlaps,
        too_short=sum(1 for c in cues if c.duration < min_ms),
        long_lines=sum(1 for c in cues for line in c.text.split("\n") if len(_TAGS.sub("", line)) > max_line),
        unsorted=unsorted,
        empty=sum(1 for c in cues if not c.text.strip()),
        with_tags=sum(1 for c in cues if _TAGS.search(c.text)),
    )
