"""Чтение и запись SRT и WebVTT."""

import re
from dataclasses import dataclass, field

from .timecode import TimecodeError, format_srt, format_vtt, parse_clock

_TIMING = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)(.*)$")
_VTT_SKIP_BLOCKS = ("NOTE", "STYLE", "REGION")


class SubtitleError(ValueError):
    """Файл не удалось разобрать как субтитры."""


@dataclass
class Cue:
    start: int
    end: int
    text: str
    settings: str = field(default="", compare=False)

    @property
    def duration(self) -> int:
        return self.end - self.start


def detect_format(text: str) -> str:
    return "vtt" if text.lstrip("﻿").lstrip().startswith("WEBVTT") else "srt"


def _blocks(text: str) -> list[list[str]]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return [block.split("\n") for block in re.split(r"\n[ \t]*\n", text.strip()) if block.strip()]


def _parse_timing(line: str, line_no: int) -> tuple[int, int, str]:
    match = _TIMING.match(line)
    try:
        start, end = parse_clock(match.group(1)), parse_clock(match.group(2))
    except TimecodeError as exc:
        raise SubtitleError(f"блок {line_no}: {exc}") from None
    if end < start:
        end = start
    return start, end, match.group(3).strip()


def parse(text: str, fmt: str | None = None) -> list[Cue]:
    fmt = fmt or detect_format(text)
    blocks = _blocks(text)
    if fmt == "vtt" and blocks and blocks[0][0].lstrip("﻿").startswith("WEBVTT"):
        blocks = blocks[1:]
    cues: list[Cue] = []
    for number, lines in enumerate(blocks, start=1):
        if fmt == "vtt" and lines[0].split(" ", 1)[0] in _VTT_SKIP_BLOCKS:
            continue
        timing_at = next((i for i, line in enumerate(lines[:3]) if "-->" in line), None)
        if timing_at is None:
            raise SubtitleError(f"блок {number}: не найдена строка времени «00:00:01,000 --> 00:00:02,000»")
        start, end, settings = _parse_timing(lines[timing_at], number)
        body = "\n".join(line.rstrip() for line in lines[timing_at + 1:])
        cues.append(Cue(start, end, body, settings if fmt == "vtt" else ""))
    if not cues:
        raise SubtitleError("в файле нет ни одного субтитра")
    return cues


def dump_srt(cues: list[Cue]) -> str:
    parts = [f"{i}\n{format_srt(c.start)} --> {format_srt(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)]
    return "\n".join(parts)


def dump_vtt(cues: list[Cue]) -> str:
    parts = ["WEBVTT\n"]
    for cue in cues:
        settings = f" {cue.settings}" if cue.settings else ""
        parts.append(f"{format_vtt(cue.start)} --> {format_vtt(cue.end)}{settings}\n{cue.text}\n")
    return "\n".join(parts)


def dump(cues: list[Cue], fmt: str) -> str:
    if fmt == "vtt":
        return dump_vtt(cues)
    if fmt == "srt":
        return dump_srt(cues)
    raise SubtitleError(f"неизвестный формат: {fmt}")
