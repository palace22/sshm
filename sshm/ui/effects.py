"""Small, old-school terminal effects: the logo, typing, spinners, status tags.

Every effect degrades to plain output when stdout is not a terminal, when
``SSHM_NO_ANIM`` is set, or on a dumb terminal, so scripts and pipes are
never slowed down.
"""

import os
import time
from typing import ContextManager, Dict, Iterator, List, Optional

from rich.console import Console
from rich.live import Live
from rich.status import Status
from rich.style import Style
from rich.text import Text

# 6-pixel-tall font, drawn with half blocks into 3 text rows.
_FONT: Dict[str, List[str]] = {
    "s": ["####", "#...", "####", "...#", "####", "...."],
    "h": ["#...", "#...", "####", "#..#", "#..#", "...."],
    "m": [".....", "#####", "#.#.#", "#.#.#", "#.#.#", "....."],
}
_HALF_BLOCKS = {("#", "#"): "█", ("#", "."): "▀", (".", "#"): "▄", (".", "."): " "}
# "left": each row starts one column further right, so the word leans back.
# "right": classic italic.
LEAN = "right"

_ASCII_LOGO = [r" ___ ___| |_  _ __", r"(_-<(_-<| ' \| '  \ ", r"/__//__/|_||_|_|_|_|"]
# No colours: the logo uses the terminal's text colour; the beam is bold.
_BEAM = Style(bold=True)


def enabled(console: Console) -> bool:
    return (
        console.is_terminal
        and not console.is_dumb_terminal
        and not os.environ.get("SSHM_NO_ANIM")
    )


def _pixel_logo(word: str = "sshm") -> List[str]:
    pixels = [".".join(_FONT[ch][row] for ch in word) for row in range(len(_FONT["s"]))]
    lines = [
        "".join(_HALF_BLOCKS[pair] for pair in zip(pixels[r], pixels[r + 1]))
        for r in range(0, len(pixels), 2)
    ]
    last = len(lines) - 1
    return [
        " " * (i if LEAN == "left" else last - i) + line for i, line in enumerate(lines)
    ]


def logo_lines(console: Console) -> List[str]:
    """The logo as plain lines: half blocks, or ASCII on non-UTF-8 terminals."""
    if console.encoding.lower().startswith("utf"):
        return _pixel_logo()
    return _ASCII_LOGO


def logo(console: Console, reveal: Optional[int] = None) -> Text:
    """The logo; with ``reveal`` only columns up to it are drawn, the last one
    in bold as the "beam", like a CRT tracing it."""
    lines = logo_lines(console)
    width = max(len(line) for line in lines)
    text = Text(no_wrap=True, overflow="crop")
    for row, line in enumerate(lines):
        for x, ch in enumerate(line.ljust(width)):
            if ch == " " or (reveal is not None and x > reveal):
                text.append(" ")
            else:
                text.append(ch, _BEAM if x == reveal else "")
        if row < len(lines) - 1:
            text.append("\n")
    return text


def logo_frames(console: Console) -> Iterator[Text]:
    """Frames of the beam sweeping across the logo (last frame = full logo)."""
    width = max(len(line) for line in logo_lines(console))
    for reveal in range(0, width, 2):
        yield logo(console, reveal)
    yield logo(console)


def tagline(version: str, *extra: str) -> Text:
    text = Text.assemble((" ssh config manager", "dim"), (" :: ", "dim"))
    text.append(f"v{version}")
    for item in extra:
        text.append(" :: ", "dim")
        text.append(item, "dim")
    return text


def banner(console: Console, version: str) -> None:
    """Sweep the logo in, then type the tagline."""
    if not enabled(console):
        console.print(logo(console))
        console.print(tagline(version))
        return
    with Live(console=console, auto_refresh=False) as live:
        for frame in logo_frames(console):
            live.update(frame, refresh=True)
            time.sleep(0.02)
    typewriter(console, tagline(version), duration=0.25)


def typewriter(console: Console, text: Text, duration: float = 0.3) -> None:
    """Print ``text`` one character at a time, finishing within ``duration``."""
    if not enabled(console) or not text.plain:
        console.print(text)
        return
    delay = min(0.015, duration / len(text.plain))
    for i in range(len(text.plain)):
        console.print(text[i : i + 1], end="")
        console.file.flush()
        time.sleep(delay)
    console.print()


def spinner(console: Console, message: str) -> ContextManager[Status]:
    """Classic ``| / - \\`` spinner while something slow runs."""
    return console.status(Text(message, style="dim"), spinner="line")


def ok(console: Console, message: str) -> None:
    """Init-script style ``[ OK ]`` status line."""
    console.print(Text.assemble("[", (" OK ", "bold green"), "] ", message))


def fail(console: Console, message: str) -> None:
    console.print(Text.assemble("[", ("FAIL", "bold red"), "] ", message))
