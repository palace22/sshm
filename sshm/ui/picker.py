"""Interactive, full-screen host picker.

Type to fuzzy-filter, ``@tag`` and ``/folder`` narrow the list. Arrows (or
ctrl-p / ctrl-n) move the inverse-video bar, tab marks hosts to open together
as tabs, enter picks, esc cancels. The mouse works too: click a row to select
it, click it again to connect, scroll with the wheel.
Works on POSIX terminals (termios) and Windows consoles (msvcrt, no mouse).
"""

import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Union

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .. import __version__
from ..models import SSHConnection
from . import effects
from .tables import tag_text, target_text

Scorer = Callable[[str, SSHConnection], int]
MIN_SCORE = 60
HINTS = [
    ("sshm --help", "all commands"),
    ("sshm man", "manual"),
    ("sshm add", "new host"),
    ("sshm open @tag", "tabs"),
]


def filter_connections(
    connections: List[SSHConnection], query: str, score: Scorer
) -> List[SSHConnection]:
    """Apply a picker query: ``@tag`` / ``/folder`` prefixes, then fuzzy text.

    Without text the input order is kept (callers pass recent-first order).
    """
    words = []
    result = connections
    for token in query.split():
        if token.startswith("@") and len(token) > 1:
            tag = token[1:].lower()
            result = [
                c for c in result if any(t.lower().startswith(tag) for t in c.tags)
            ]
        elif token.startswith("/") and len(token) > 1:
            folder = token[1:].lower()
            result = [c for c in result if (c.folder or "").lower().startswith(folder)]
        else:
            words.append(token)

    text = " ".join(words)
    if not text:
        return result
    scored = [(c, score(text, c)) for c in result]
    scored = [item for item in scored if item[1] >= MIN_SCORE]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [c for c, _ in scored]


def supported() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if os.name == "nt":
        return True
    try:
        import termios  # noqa: F401
    except ImportError:
        return False
    return True


# ------------------------------------------------------------------ input


@dataclass
class Mouse:
    """A mouse event; ``x``/``y`` are 1-based screen coordinates."""

    button: int
    x: int
    y: int
    pressed: bool


Key = Union[str, Mouse]

WHEEL_UP, WHEEL_DOWN, LEFT_BUTTON = 64, 65, 0
_MOUSE_ON = "\x1b[?1000h\x1b[?1006h"  # button events, SGR encoding
_MOUSE_OFF = "\x1b[?1000l\x1b[?1006l"
_SGR_MOUSE = re.compile(r"\[<(\d+);(\d+);(\d+)([Mm])")
_ESCAPES = {
    "[A": "up",
    "OA": "up",
    "[B": "down",
    "OB": "down",
    "[Z": "up",  # shift-tab
    "[5~": "pageup",
    "[6~": "pagedown",
}
_CONTROL = {
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x10": "up",  # ctrl-p
    "\x0e": "down",  # ctrl-n
    "\t": "mark",
    "\x15": "clear",  # ctrl-u
    "\x17": "word",  # ctrl-w
    "\x03": "esc",  # ctrl-c
    "\x04": "esc",  # ctrl-d
}


def _parse_keys(data: str) -> Iterator[Key]:
    """Turn raw terminal input into key names, printable chars or Mouse events."""
    i = 0
    while i < len(data):
        ch = data[i]
        if ch != "\x1b":
            if ch in _CONTROL:
                yield _CONTROL[ch]
            elif ch.isprintable():
                yield ch
            i += 1
            continue

        rest = data[i + 1 :]
        mouse = _SGR_MOUSE.match(rest)
        if mouse:
            button, x, y, kind = mouse.groups()
            yield Mouse(int(button), int(x), int(y), kind == "M")
            i += 1 + mouse.end()
            continue
        for seq, key in _ESCAPES.items():
            if rest.startswith(seq):
                yield key
                i += 1 + len(seq)
                break
        else:
            if rest[:1] in ("[", "O"):
                # Unknown sequence (left/right, F-keys...): skip it.
                j = i + 2
                while j < len(data) and not (data[j].isalpha() or data[j] == "~"):
                    j += 1
                i = j + 1
            else:
                yield "esc"
                i += 1


class _PosixKeyboard:
    def __enter__(self) -> "_PosixKeyboard":
        import termios
        import tty

        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        # cbreak, not raw: output post-processing (\n -> \r\n) stays on, so
        # Rich renders normally. ISIG is turned off so ctrl-c arrives as a key.
        tty.setcbreak(self.fd)
        attrs = termios.tcgetattr(self.fd)
        attrs[3] &= ~termios.ISIG
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        sys.stdout.write(_MOUSE_ON)
        sys.stdout.flush()
        return self

    def __exit__(self, *exc: object) -> None:
        import termios

        sys.stdout.write(_MOUSE_OFF)
        sys.stdout.flush()
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def read(self) -> List[Key]:
        return list(_parse_keys(os.read(self.fd, 256).decode("utf-8", "ignore")))


class _WindowsKeyboard:
    _SPECIAL = {"H": "up", "P": "down", "I": "pageup", "Q": "pagedown"}

    def __enter__(self) -> "_WindowsKeyboard":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def read(self) -> List[Key]:
        import msvcrt

        ch = msvcrt.getwch()  # type: ignore[attr-defined]
        if ch in ("\x00", "\xe0"):
            return [self._SPECIAL.get(msvcrt.getwch(), "")]  # type: ignore[attr-defined]
        return list(_parse_keys(ch))


# ------------------------------------------------------------------- view


class Picker:
    def __init__(
        self,
        connections: List[SSHConnection],
        score: Scorer,
        console: Console,
        query: str = "",
        title: str = "",
    ):
        self.connections = connections
        self.score = score
        self.console = console
        self.query = query
        self.title = title
        self.selected = 0
        self.offset = 0
        self.marked: List[str] = []
        self.matches = filter_connections(connections, query, score)

    # Layout: [logo(3) + tagline + blank] + query + rule | rows | rule + status + hints
    @property
    def show_logo(self) -> bool:
        return self.console.size.height >= 18

    @property
    def top(self) -> int:
        """Screen lines above the first host row."""
        return (5 if self.show_logo else 1) + 2

    @property
    def rows(self) -> int:
        return max(1, self.console.size.height - self.top - 3)

    def chosen(self) -> List[SSHConnection]:
        """Marked hosts (in marking order), else the selected one."""
        if self.marked:
            by_name = {c.name: c for c in self.connections}
            return [by_name[name] for name in self.marked]
        return [self.matches[self.selected]] if self.matches else []

    def _refilter(self) -> None:
        self.matches = filter_connections(self.connections, self.query, self.score)
        self.selected = 0
        self.offset = 0

    def _move(self, delta: int) -> None:
        if not self.matches:
            return
        self.selected = max(0, min(len(self.matches) - 1, self.selected + delta))
        if self.selected < self.offset:
            self.offset = self.selected
        elif self.selected >= self.offset + self.rows:
            self.offset = self.selected - self.rows + 1

    def _click(self, event: Mouse) -> Optional[str]:
        if event.button == WHEEL_UP:
            self._move(-3)
        elif event.button == WHEEL_DOWN:
            self._move(3)
        elif event.button == LEFT_BUTTON and event.pressed:
            row = event.y - 1 - self.top
            index = self.offset + row
            if 0 <= row < self.rows and index < len(self.matches):
                if index == self.selected:
                    return "pick"
                self.selected = index
        return None

    def handle(self, key: Key) -> Optional[str]:
        """Apply one key. Returns 'pick' or 'cancel' when the picker is done."""
        if isinstance(key, Mouse):
            return self._click(key)
        if key == "enter":
            return "pick" if self.chosen() else None
        if key == "esc":
            return "cancel"
        if key in ("up", "down", "pageup", "pagedown"):
            step = {"up": -1, "down": 1, "pageup": -self.rows, "pagedown": self.rows}
            self._move(step[key])
            return None
        if key == "mark":
            if self.matches:
                name = self.matches[self.selected].name
                if name in self.marked:
                    self.marked.remove(name)
                else:
                    self.marked.append(name)
                self._move(1)
            return None
        if key == "backspace":
            self.query = self.query[:-1]
        elif key == "clear":
            self.query = ""
        elif key == "word":
            self.query = self.query.rstrip().rpartition(" ")[0]
            self.query += " " if self.query else ""
        elif len(key) == 1:
            self.query += key
        else:
            return None
        self._refilter()
        return None

    def _line(self, *parts: object) -> Text:
        text = Text.assemble(*parts)  # type: ignore[arg-type]
        text.no_wrap = True
        text.overflow = "ellipsis"
        return text

    def _status(self) -> Text:
        total = len(self.connections)
        action = f"open {len(self.marked)} tabs" if len(self.marked) > 1 else "connect"
        parts: List[object] = [(f"  {len(self.matches)}/{total}", "bold")]
        if self.marked:
            parts.append((f"  {len(self.marked)} marked", "magenta"))
        parts.append(
            (
                f"   up/down move   tab mark   enter {action}   "
                "@tag /folder filter   esc quit",
                "dim",
            )
        )
        return self._line(*parts)

    def _hints(self) -> Text:
        parts: List[object] = [" "]
        for command, meaning in HINTS:
            parts += [(f" {command}", "cyan"), (f" {meaning}  ", "dim")]
        return self._line(*parts)

    def render(self, logo: Optional[Text] = None) -> Group:
        header: List[RenderableType] = []
        info = [f"{len(self.connections)} hosts"] + ([self.title] if self.title else [])
        if self.show_logo:
            header += [
                logo or effects.logo(self.console),
                effects.tagline(__version__, *info),
                Text(""),
            ]
        else:
            header.append(
                self._line(
                    (" sshm ", "reverse bold"), (f"  {' :: '.join(info)}", "dim")
                )
            )
        prompt = self._line(("> ", "bold cyan"), self.query, ("_", "blink"))

        table = Table.grid(padding=(0, 2))
        for style in ("bold", "", "blue", "magenta"):
            table.add_column(style=style, no_wrap=True, overflow="ellipsis")
        window = self.matches[self.offset : self.offset + self.rows]
        for i, conn in enumerate(window, start=self.offset):
            cursor = ">" if i == self.selected else " "
            mark = "*" if conn.name in self.marked else " "
            table.add_row(
                f"{cursor}{mark} {conn.name}",
                target_text(conn),
                conn.folder or "",
                tag_text(conn.tags),
                style="reverse" if i == self.selected else None,
            )
        if not self.matches:
            table.add_row(Text("   no match", style="dim"), "", "", "")
        shown = len(window) or 1
        # Pad so the footer stays at the bottom (a Text of n newlines is n+1 lines).
        filler = [Text("\n" * (self.rows - shown - 1))] if self.rows > shown else []

        rule = Rule(style="dim")
        return Group(
            *header, prompt, rule, table, *filler, rule, self._status(), self._hints()
        )

    def run(self) -> List[SSHConnection]:
        keyboard = _WindowsKeyboard() if os.name == "nt" else _PosixKeyboard()
        with (
            keyboard,
            Live(
                self.render(),
                console=self.console,
                screen=True,
                auto_refresh=False,
            ) as live,
        ):
            if self.show_logo and effects.enabled(self.console):
                for frame in effects.logo_frames(self.console):
                    live.update(self.render(logo=frame), refresh=True)
                    time.sleep(0.015)
            while True:
                for key in keyboard.read():
                    action = self.handle(key)
                    if action == "cancel":
                        return []
                    if action == "pick":
                        return self.chosen()
                live.update(self.render(), refresh=True)


def pick(
    connections: List[SSHConnection],
    score: Scorer,
    console: Console,
    query: str = "",
    title: str = "",
) -> List[SSHConnection]:
    """Run the picker; returns the chosen hosts (empty if cancelled)."""
    return Picker(connections, score, console, query, title).run()
