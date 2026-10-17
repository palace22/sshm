"""Picker filtering and key handling (no terminal needed)."""

from rich.console import Console

from sshm.manager import SSHManager
from sshm.models import AppConfig, SSHConnection
from sshm.ui.picker import (
    LEFT_BUTTON,
    WHEEL_DOWN,
    Mouse,
    Picker,
    _parse_keys,
    filter_connections,
)

CONNS = [
    SSHConnection(name="web-prod", hostname="10.0.0.1", tags=["prod", "web"]),
    SSHConnection(name="db-prod", hostname="10.0.0.2", tags=["prod"], folder="work"),
    SSHConnection(name="laptop", hostname="192.168.1.5"),
]
score = SSHManager(AppConfig()).score


def names(conns):
    return [c.name for c in conns]


def test_empty_query_keeps_order():
    assert names(filter_connections(CONNS, "", score)) == [
        "web-prod",
        "db-prod",
        "laptop",
    ]


def test_tag_and_folder_tokens():
    assert names(filter_connections(CONNS, "@pro", score)) == ["web-prod", "db-prod"]
    assert names(filter_connections(CONNS, "@prod /work", score)) == ["db-prod"]


def test_fuzzy_text_ranks_best_first():
    assert names(filter_connections(CONNS, "lap", score))[0] == "laptop"
    assert filter_connections(CONNS, "zzzz", score) == []


def test_parse_keys():
    keys = list(_parse_keys("ab\x1b[A\x1b[B\x1b[C\r\x7f\x1b"))
    assert keys == ["a", "b", "up", "down", "enter", "backspace", "esc"]


def test_picker_navigation_and_typing():
    p = Picker(CONNS, score, Console(width=80, height=30))
    p.handle("down")
    p.handle("down")
    p.handle("down")  # clamps at the last row
    assert p.matches[p.selected].name == "laptop"
    for ch in "@prod":
        p.handle(ch)
    assert names(p.matches) == ["web-prod", "db-prod"] and p.selected == 0
    p.handle("word")
    assert p.query == ""
    assert p.handle("enter") == "pick"
    assert p.handle("esc") == "cancel"


def test_parse_mouse_and_tab():
    keys = list(_parse_keys("\t\x1b[<0;5;9M\x1b[<65;5;9M\x1b[<0;5;9m"))
    assert keys == [
        "mark",
        Mouse(LEFT_BUTTON, 5, 9, True),
        Mouse(WHEEL_DOWN, 5, 9, True),
        Mouse(LEFT_BUTTON, 5, 9, False),
    ]


def test_tab_marks_hosts_in_order():
    p = Picker(CONNS, score, Console(width=80, height=30))
    p.handle("down")
    p.handle("mark")  # db-prod, cursor moves to laptop
    p.handle("mark")  # laptop (last row: the cursor stays on it)
    assert names(p.chosen()) == ["db-prod", "laptop"]
    p.handle("mark")  # unmark laptop
    assert names(p.chosen()) == ["db-prod"]


def test_click_selects_then_picks():
    p = Picker(CONNS, score, Console(width=80, height=30))
    second_row_y = p.top + 2  # 1-based screen line of the second host
    assert p.handle(Mouse(LEFT_BUTTON, 3, second_row_y, True)) is None
    assert p.matches[p.selected].name == "db-prod"
    assert p.handle(Mouse(LEFT_BUTTON, 3, second_row_y, True)) == "pick"
    assert p.handle(Mouse(LEFT_BUTTON, 3, 1, True)) is None  # logo area: ignored


def test_render_fills_exactly_the_screen():
    console = Console(width=80, height=30, record=True)
    p = Picker(CONNS, score, console)
    lines = console.render_lines(p.render(), console.options)
    assert len(lines) == 30


def test_small_screen_drops_logo():
    p = Picker(CONNS, score, Console(width=80, height=12))
    assert not p.show_logo and p.top == 3
