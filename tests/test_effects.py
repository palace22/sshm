"""Logo rendering."""

import io

from rich.console import Console

from sshm.ui import effects


def console(encoding="utf-8"):
    return Console(file=io.TextIOWrapper(io.BytesIO(), encoding=encoding), width=80)


def test_logo_is_three_leaning_rows():
    lines = effects.logo_lines(console())
    assert len(lines) == 3
    indents = [len(line) - len(line.lstrip()) for line in lines]
    assert indents == ([0, 1, 2] if effects.LEAN == "left" else [2, 1, 0])


def test_ascii_fallback_on_non_utf8():
    assert all(line.isascii() for line in effects.logo_lines(console("ascii")))


def test_reveal_frames_end_with_full_logo():
    c = console()
    frames = list(effects.logo_frames(c))
    assert len(frames) > 5
    assert frames[-1].plain == effects.logo(c).plain
    assert frames[0].plain.count("█") < frames[-1].plain.count("█")
