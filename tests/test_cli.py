from pathlib import Path

from subfix.cli import main

SAMPLE = Path(__file__).parent.parent / "examples" / "sample-cp1251.srt"


def make(tmp_path, text, name="film.srt", enc="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(enc))
    return path


SRT = "1\n00:00:10,000 --> 00:00:12,000\nПервый\n\n2\n00:01:40,000 --> 00:01:42,000\nВторой\n"


def test_shift_negative_offset_writes_fixed_copy(tmp_path):
    src = make(tmp_path, SRT)
    assert main(["shift", str(src), "--by", "-2s"]) == 0
    out = (tmp_path / "film.fixed.srt").read_text("utf-8")
    assert "00:00:08,000 --> 00:00:10,000" in out
    assert src.read_text("utf-8") == SRT


def test_in_place_and_crlf(tmp_path):
    src = make(tmp_path, SRT)
    assert main(["shift", str(src), "--by", "+500ms", "-i", "--crlf"]) == 0
    data = src.read_bytes()
    assert b"00:00:10,500 --> 00:00:12,500\r\n" in data


def test_sync_by_cue_numbers(tmp_path):
    src = make(tmp_path, SRT)
    out = tmp_path / "synced.srt"
    assert main(["sync", str(src), "-p", "#1=00:00:11,000", "-p", "#2=00:01:44,000", "-o", str(out)]) == 0
    text = out.read_text("utf-8")
    assert "00:00:11,000 -->" in text and "00:01:44,000 -->" in text


def test_convert_cp1251_sample_to_vtt_utf8(tmp_path):
    out = tmp_path / "sample.vtt"
    assert main(["convert", str(SAMPLE), "-t", "vtt", "-o", str(out)]) == 0
    text = out.read_text("utf-8")
    assert text.startswith("WEBVTT")
    assert "Где ты был всю ночь?" in text


def test_clean_all_flags(tmp_path, capsys):
    out = tmp_path / "clean.srt"
    assert main(["clean", str(SAMPLE), "--tags", "--sdh", "--min-duration", "800", "-o", str(out)]) == 0
    text = out.read_text("utf-8")
    assert "<i>" not in text and "{\\an8}" not in text and "[дверь" not in text and "(музыка)" not in text
    assert text.count("-->") == 4
    assert "исправлено наложений: 1" in capsys.readouterr().err


def test_fps(tmp_path):
    src = make(tmp_path, SRT)
    assert main(["fps", str(src), "--from", "25", "--fps", "23,976", "-o", "-"]) == 0


def test_info(capsys):
    assert main(["info", str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "cp1251" in out and "Наложений         1" in out


def test_errors_are_reported(tmp_path, capsys):
    src = make(tmp_path, SRT)
    assert main(["shift", str(tmp_path / "missing.srt"), "--by", "1"]) == 1
    assert main(["sync", str(src), "-p", "#7=00:00:01,000"]) == 1
    assert main(["shift", str(src), "--by", "много"]) == 1
    broken = make(tmp_path, "это не субтитры", "broken.srt")
    assert main(["info", str(broken)]) == 1
    err = capsys.readouterr().err
    assert "файл не найден" in err and "нет субтитра #7" in err and "не понимаю сдвиг" in err


def test_output_flag_needs_single_file(tmp_path):
    a, b = make(tmp_path, SRT, "a.srt"), make(tmp_path, SRT, "b.srt")
    assert main(["convert", str(a), str(b), "-o", str(tmp_path / "x.srt")]) == 2
    assert main(["convert", str(a), str(b), "-t", "vtt"]) == 0
    assert (tmp_path / "a.fixed.vtt").exists() and (tmp_path / "b.fixed.vtt").exists()


def test_plural():
    from subfix.cli import plural
    assert [plural(n, "субтитр", "субтитра", "субтитров") for n in (1, 3, 5, 11, 21, 112)] == [
        "1 субтитр", "3 субтитра", "5 субтитров", "11 субтитров", "21 субтитр", "112 субтитров",
    ]
