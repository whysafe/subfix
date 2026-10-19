"""Командная строка subfix."""

import argparse
import re
import sys
from pathlib import Path

from . import __version__, encoding, formats, ops
from .formats import Cue, SubtitleError
from .timecode import TimecodeError, format_human, parse_clock, parse_offset

# argparse принимает «-2s» за неизвестный флаг. Отрицательные сдвиги заменяем
# на знак минуса U+2212 до разбора, parse_offset понимает оба варианта.
_NEGATIVE = re.compile(r"^-\d[\d.,:]*(ms|s|m|h)?$")


class CliError(Exception):
    pass


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def _read(path: Path, forced_encoding: str | None) -> tuple[list[Cue], str, str]:
    if not path.is_file():
        raise CliError(f"файл не найден: {path}")
    text, used = encoding.decode(path.read_bytes(), forced_encoding)
    fmt = "vtt" if path.suffix.lower() == ".vtt" else formats.detect_format(text)
    return formats.parse(text, fmt), used, fmt


def _target(path: Path, args, fmt: str) -> Path | None:
    if args.output == "-":
        return None
    if args.output:
        return Path(args.output)
    if args.in_place:
        return path.with_suffix(f".{fmt}")
    return path.with_name(f"{path.stem}.fixed.{fmt}")


def _write(cues: list[Cue], path: Path, args, src_fmt: str, used_enc: str) -> None:
    fmt = args.to or src_fmt
    text = formats.dump(cues, fmt)
    if args.crlf:
        text = text.replace("\n", "\r\n")
    target = _target(path, args, fmt)
    if target is None:
        sys.stdout.write(text)
        return
    target.write_bytes(text.encode(args.out_encoding))
    same = used_enc.replace("-sig", "") == args.out_encoding.lower().replace("_", "-")
    note = "" if same else f", кодировка {used_enc} -> {args.out_encoding}"
    count = plural(len(cues), "субтитр", "субтитра", "субтитров")
    print(f"{path.name} -> {target}  ({count}{note})", file=sys.stderr)


def _sync_point(text: str, cues: list[Cue]) -> ops.SyncPoint:
    if "=" not in text:
        raise CliError(f"опорная точка пишется как СЕЙЧАС=НУЖНО, например #12=00:01:05,300; получено {text!r}")
    current, correct = (part.strip() for part in text.split("=", 1))
    if current.startswith("#"):
        try:
            index = int(current[1:])
        except ValueError:
            raise CliError(f"номер субтитра должен быть числом: {current!r}") from None
        if not 1 <= index <= len(cues):
            raise CliError(f"в файле нет субтитра {current}, всего их {len(cues)}")
        current_ms = cues[index - 1].start
    else:
        current_ms = parse_clock(current)
    return ops.SyncPoint(current_ms, parse_clock(correct))


def cmd_info(cues: list[Cue], args, enc: str, fmt: str, path: Path) -> None:
    report = ops.analyze(cues, max_line=args.max_line)
    rows = [
        ("Файл", str(path)),
        ("Формат", fmt.upper()),
        ("Кодировка", enc),
        ("Субтитров", str(report.count)),
        ("Начало", format_human(report.first_ms)),
        ("Конец", format_human(report.last_ms)),
        ("Наложений", str(report.overlaps)),
        ("Не по порядку", str(report.unsorted)),
        ("Короче 0,7 с", str(report.too_short)),
        (f"Строк длиннее {args.max_line}", str(report.long_lines)),
        ("С тегами", str(report.with_tags)),
        ("Пустых", str(report.empty)),
    ]
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name.ljust(width)}  {value}")
    hints = []
    if report.overlaps or report.unsorted or report.empty:
        hints.append(f"subfix clean {path.name}  - починит наложения, порядок и пустые блоки")
    if enc not in ("utf-8", "utf-8-sig"):
        hints.append(f"subfix convert {path.name}  - сохранит в UTF-8, чтобы телевизор не показывал «кракозябры»")
    if hints:
        print("Совет:\n  " + "\n  ".join(hints))


def cmd_shift(cues, args):
    offset = parse_offset(args.offset)
    after = parse_clock(args.after) if args.after else 0
    return ops.shift(cues, offset, after)


def cmd_sync(cues, args):
    points = [_sync_point(p, cues) for p in args.point]
    if len(points) == 1:
        return ops.shift(cues, points[0].correct_ms - points[0].current_ms)
    if len(points) != 2:
        raise CliError("нужны одна или две опорные точки --point")
    result, scale, offset = ops.two_point_sync(cues, *points)
    print(f"масштаб {scale:.6f}, сдвиг {format_human(round(offset))}", file=sys.stderr)
    return result


def cmd_fps(cues, args):
    return ops.change_fps(cues, args.source, args.target)


def cmd_convert(cues, args):
    return cues


def cmd_clean(cues, args):
    if args.tags:
        cues = ops.strip_tags(cues)
    if args.sdh:
        cues = ops.strip_sdh(cues)
    before = len(cues)
    cues = ops.drop_empty(cues)
    if args.min_duration:
        cues, extended = ops.extend_short(cues, args.min_duration)
        print(f"удлинено коротких: {extended}", file=sys.stderr)
    cues, fixed = ops.fix_overlaps(cues)
    print(f"удалено пустых: {before - len(cues)}, исправлено наложений: {fixed}", file=sys.stderr)
    return cues


def _fps_value(text: str) -> float:
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"не число: {text!r}") from None
    if not 1 <= value <= 240:
        raise argparse.ArgumentTypeError("частота кадров должна быть от 1 до 240")
    return value


def _positive_ms(text: str) -> int:
    if not text.isdigit() or int(text) == 0:
        raise argparse.ArgumentTypeError("нужно целое число миллисекунд больше нуля")
    return int(text)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("files", nargs="+", type=Path, metavar="FILE", help="файлы .srt или .vtt")
    common.add_argument("-e", "--encoding", help="кодировка входа, по умолчанию определяется сама")

    output = argparse.ArgumentParser(add_help=False)
    out = output.add_argument_group("вывод")
    out.add_argument("-o", "--output", help="куда сохранить, «-» для вывода в консоль (только для одного файла)")
    out.add_argument("-i", "--in-place", action="store_true", help="перезаписать исходный файл")
    out.add_argument("-t", "--to", choices=("srt", "vtt"), help="формат результата")
    out.add_argument("--out-encoding", default="utf-8", help="кодировка результата (по умолчанию utf-8)")
    out.add_argument("--crlf", action="store_true", help="переводы строк Windows (CRLF)")

    parser = argparse.ArgumentParser(
        prog="subfix",
        description="Чинит субтитры: сдвиг, синхронизация по двум точкам, FPS, кодировка, SRT и VTT.",
    )
    parser.add_argument("--version", action="version", version=f"subfix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="КОМАНДА")

    info = sub.add_parser("info", parents=[common], help="показать сводку и проблемы файла")
    info.add_argument("--max-line", type=int, default=42, help="порог длинной строки (по умолчанию 42)")

    shift = sub.add_parser("shift", parents=[common, output], help="сдвинуть всё время")
    shift.add_argument("--by", dest="offset", required=True, metavar="СДВИГ",
                       help="на сколько: 2.5, -1500ms, +00:00:03,000 (минус = раньше)")
    shift.add_argument("--after", metavar="TIME", help="сдвигать только начиная с этого времени")

    sync = sub.add_parser("sync", parents=[common, output], help="синхронизация по одной или двум опорным точкам")
    sync.add_argument("-p", "--point", action="append", required=True, metavar="СЕЙЧАС=НУЖНО",
                      help="#номер_субтитра=время или время=время, можно указать дважды")

    fps = sub.add_parser("fps", parents=[common, output], help="пересчитать под другую частоту кадров")
    fps.add_argument("--from", dest="source", type=_fps_value, required=True, help="частота, под которую сделаны субтитры")
    fps.add_argument("--fps", dest="target", type=_fps_value, required=True, help="частота вашего видео")

    sub.add_parser("convert", parents=[common, output], help="сменить формат или кодировку")

    clean = sub.add_parser("clean", parents=[common, output], help="порядок, наложения, пустые блоки, теги, SDH")
    clean.add_argument("--tags", action="store_true", help="убрать <i>, <font>, {\\an8}")
    clean.add_argument("--sdh", action="store_true", help="убрать [смех], (шум), ♪ и «ИМЯ:»")
    clean.add_argument("--min-duration", type=_positive_ms, metavar="MS", help="удлинить субтитры короче MS миллисекунд")
    return parser


COMMANDS = {"shift": cmd_shift, "sync": cmd_sync, "fps": cmd_fps, "convert": cmd_convert, "clean": cmd_clean}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = ["−" + a[1:] if _NEGATIVE.match(a) else a for a in argv]
    args = build_parser().parse_args(argv)
    if args.command != "info" and len(args.files) > 1 and args.output:
        print("subfix: ошибка: -o можно указать только для одного файла", file=sys.stderr)
        return 2
    failed = 0
    for number, path in enumerate(args.files):
        try:
            cues, enc, fmt = _read(path, args.encoding)
            if args.command == "info":
                if number:
                    print()
                cmd_info(cues, args, enc, fmt, path)
                continue
            _write(COMMANDS[args.command](cues, args), path, args, fmt, enc)
        except (CliError, SubtitleError, TimecodeError, ValueError, LookupError, OSError) as exc:
            print(f"subfix: {path.name}: ошибка: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
