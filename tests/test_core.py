import pytest

from subfix import encoding, formats, ops
from subfix.formats import Cue, SubtitleError
from subfix.timecode import TimecodeError, format_human, format_srt, parse_clock, parse_offset

SRT = """﻿1
00:00:01,000 --> 00:00:03,000
Привет!

2
00:00:02,500 --> 00:00:05,000
<i>Как дела?</i>
Нормально.

3
00:01:00,000 --> 00:01:02,000
Пока.
"""

VTT = """WEBVTT
Kind: captions

NOTE это комментарий

intro
00:01.000 --> 00:03.000 align:start
Hello

00:00:04.500 --> 00:00:06.000
World
"""


@pytest.mark.parametrize("text, ms", [
    ("00:00:01,000", 1000),
    ("01:02:03,456", 3723456),
    ("02:03.5", 123500),
    ("1:00:00", 3600000),
    ("00:00:00.07", 70),
])
def test_parse_clock(text, ms):
    assert parse_clock(text) == ms


@pytest.mark.parametrize("bad", ["", "abc", "00:61:00,000", "1:2:3:4"])
def test_parse_clock_rejects(bad):
    with pytest.raises(TimecodeError):
        parse_clock(bad)


@pytest.mark.parametrize("text, ms", [
    ("2.5", 2500), ("+2,5", 2500), ("-1500ms", -1500), ("3s", 3000),
    ("1m", 60000), ("-00:00:01,200", -1200), ("−2s", -2000),
])
def test_parse_offset(text, ms):
    assert parse_offset(text) == ms


def test_parse_offset_rejects_garbage():
    with pytest.raises(TimecodeError):
        parse_offset("пять секунд")


def test_format():
    assert format_srt(3723456) == "01:02:03,456"
    assert format_srt(-5) == "00:00:00,000"
    assert format_human(61500) == "1:01.5"


def test_parse_srt_with_bom_and_multiline():
    cues = formats.parse(SRT)
    assert len(cues) == 3
    assert cues[1].text == "<i>Как дела?</i>\nНормально."
    assert cues[2].start == 60000


def test_parse_srt_crlf_and_missing_numbers():
    text = "00:00:01,000 --> 00:00:02,000\r\nA\r\n\r\n00:00:03,000 --> 00:00:04,000\r\nB\r\n"
    cues = formats.parse(text)
    assert [c.text for c in cues] == ["A", "B"]


def test_parse_vtt_skips_header_and_notes():
    cues = formats.parse(VTT)
    assert formats.detect_format(VTT) == "vtt"
    assert [c.text for c in cues] == ["Hello", "World"]
    assert cues[0].settings == "align:start"
    assert cues[1].start == 4500


def test_parse_errors():
    with pytest.raises(SubtitleError, match="строка времени"):
        formats.parse("1\nпросто текст\n")
    with pytest.raises(SubtitleError):
        formats.parse("   \n\n")


def test_roundtrip_srt_and_vtt():
    cues = formats.parse(SRT)
    assert formats.parse(formats.dump_srt(cues)) == cues
    vtt = formats.dump_vtt(cues)
    assert vtt.startswith("WEBVTT\n\n00:00:01.000 --> 00:00:03.000")
    assert formats.parse(vtt) == cues


def test_detect_encodings():
    text = "Где ты был всю ночь? Мы опоздали на поезд."
    assert encoding.detect(text.encode("utf-8")) == "utf-8"
    assert encoding.detect(text.encode("cp1251")) == "cp1251"
    assert encoding.detect(text.encode("koi8-r")) == "koi8-r"
    assert encoding.detect("Café crème brûlée".encode("cp1252")) == "cp1252"
    assert encoding.detect(b"\xef\xbb\xbfhi") == "utf-8-sig"
    assert encoding.decode(text.encode("cp1251"))[0] == text


def test_shift_clamps_and_after():
    cues = formats.parse(SRT)
    shifted = ops.shift(cues, -2000)
    assert (shifted[0].start, shifted[0].end) == (0, 1000)
    partial = ops.shift(cues, 1000, after_ms=30000)
    assert partial[0].start == 1000 and partial[2].start == 61000


def test_fps_conversion():
    cues = [Cue(25000, 50000, "x")]
    result = ops.change_fps(cues, 25, 23.976)
    assert result[0].start == round(25000 * 25 / 23.976)
    with pytest.raises(ValueError):
        ops.change_fps(cues, 0, 25)


def test_two_point_sync_hits_both_points():
    cues = [Cue(10_000, 11_000, "a"), Cue(50_000, 51_000, "b"), Cue(100_000, 101_000, "c")]
    first, second = ops.SyncPoint(10_000, 11_000), ops.SyncPoint(100_000, 104_000)
    result, scale, _ = ops.two_point_sync(cues, first, second)
    assert result[0].start == 11_000
    assert result[2].start == 104_000
    assert scale == pytest.approx(93 / 90)
    with pytest.raises(ValueError):
        ops.two_point_sync(cues, first, ops.SyncPoint(10_000, 20_000))


def test_strip_tags_and_sdh():
    cues = [
        Cue(0, 1, "<i>Привет</i> {\\an8}<font color=\"#fff\">мир</font>"),
        Cue(1, 2, "[смех]\nДЖОН: Стой!\n(шаги)"),
        Cue(2, 3, "♪ ♪"),
        Cue(3, 4, "- [вздох]\n- Ладно."),
    ]
    assert ops.strip_tags(cues)[0].text == "Привет мир"
    sdh = ops.strip_sdh(cues)
    assert sdh[1].text == "Стой!"
    assert sdh[2].text == ""
    assert sdh[3].text == "- Ладно."
    assert len(ops.drop_empty(sdh)) == 3


def test_fix_overlaps_and_sorting():
    cues = [Cue(5000, 7000, "b"), Cue(1000, 6000, "a"), Cue(6500, 8000, "c")]
    fixed, count = ops.fix_overlaps(cues)
    assert [c.text for c in fixed] == ["a", "b", "c"]
    assert fixed[0].end == 4999 and fixed[1].end == 6499
    assert count == 2


def test_extend_short_respects_next_cue():
    cues = [Cue(0, 200, "a"), Cue(500, 600, "b")]
    result, count = ops.extend_short(cues, 1000)
    assert result[0].end == 499 and result[1].end == 1500
    assert count == 2


def test_analyze():
    report = ops.analyze(formats.parse(SRT), max_line=8)
    assert report.count == 3
    assert report.overlaps == 1
    assert report.with_tags == 1
    assert report.long_lines == 2
    assert (report.first_ms, report.last_ms) == (1000, 62000)
