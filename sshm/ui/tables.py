"""Rich renderables for connections: table, detail panel, tree, search results."""

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ..models import SSHConnection


def _truncate(value: str, max_len: int) -> str:
    return value if len(value) <= max_len else value[: max_len - 1] + "~"


def tag_text(tags: Sequence[str]) -> str:
    return " ".join(f"@{t}" for t in tags)


def target_text(conn: SSHConnection) -> str:
    port = f":{conn.port}" if conn.port != 22 else ""
    return f"{conn.target}{port}"


# (header, value getter, style); optional columns are hidden when empty.
_Column = Tuple[str, Callable[[SSHConnection], str], str]
_ALWAYS: List[_Column] = [
    ("NAME", lambda c: c.name, "bold cyan"),
    ("USER", lambda c: c.user or "-", "yellow"),
    ("HOSTNAME", lambda c: c.hostname, "green"),
    ("PORT", lambda c: str(c.port), ""),
]
_OPTIONAL: List[_Column] = [
    ("KEY", lambda c: c.identity_file.name if c.identity_file else "", "blue"),
    ("JUMP", lambda c: _truncate(c.proxy_jump or "", 18), "bright_blue"),
    ("FORWARD", lambda c: _truncate(c.local_forward or "", 18), "dim"),
    ("FOLDER", lambda c: c.folder or "", "blue"),
    ("TAGS", lambda c: tag_text(c.tags), "magenta"),
]


def connection_table(connections: Sequence[SSHConnection]) -> Table:
    """Plain table; optional columns only appear when some host uses them."""
    columns = _ALWAYS + [
        col for col in _OPTIONAL if any(col[1](c) for c in connections)
    ]
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    for header, _, style in columns:
        table.add_column(header, style=style, no_wrap=header != "TAGS")
    for conn in connections:
        table.add_row(*(getter(conn) or "-" for _, getter, _ in columns))
    return table


def connection_detail(conn: SSHConnection) -> Panel:
    """Key/value panel for one connection."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column()

    rows: List[Tuple[str, Optional[str]]] = [
        ("name", f"[bold cyan]{conn.name}[/bold cyan]"),
        ("aliases", ", ".join(conn.aliases)),
        ("hostname", conn.hostname),
        ("user", conn.user or "[dim](ssh default)[/dim]"),
        ("port", str(conn.port)),
        ("key", str(conn.identity_file) if conn.identity_file else None),
        ("jump", conn.proxy_jump),
        ("forward", conn.local_forward),
        ("folder", conn.folder),
        ("tags", f"[magenta]{tag_text(conn.tags)}[/magenta]" if conn.tags else None),
    ]
    rows += list(conn.extra_options.items())
    if conn.source:
        rows.append(("file", f"[dim]{conn.source}[/dim]"))

    for key, value in rows:
        if value:
            grid.add_row(key, value)
    return Panel(grid, box=box.SQUARE, border_style="dim", expand=False)


def compact_list(connections: Sequence[SSHConnection]) -> Columns:
    items = [
        Panel(
            f"[bold cyan]{c.name}[/bold cyan]\n[dim]{c.target}[/dim]",
            box=box.SQUARE,
            border_style="dim",
            padding=(0, 1),
        )
        for c in connections
    ]
    return Columns(items, equal=True, expand=True)


def connection_tree(
    connections: Sequence[SSHConnection], folders: Sequence[str], root_label: str
) -> Tree:
    """Folders as branches (empty ones included), hosts as leaves."""
    tree = Tree(Text(root_label, style="bold"), guide_style="dim")
    nodes: Dict[str, Tree] = {"": tree}

    def node(folder: str) -> Tree:
        if folder not in nodes:
            parent, _, leaf = folder.rpartition("/")
            nodes[folder] = node(parent).add(Text(f"{leaf}/", style="bold blue"))
        return nodes[folder]

    for folder in folders:
        node(folder)
    width = max((len(c.name) for c in connections), default=0)
    for conn in connections:
        label = Text.assemble(
            (conn.name.ljust(width), "cyan"),
            "  ",
            (target_text(conn), "dim"),
            ("  " + tag_text(conn.tags), "magenta") if conn.tags else "",
        )
        node(conn.folder or "").add(label)
    return tree


def search_results(matches: Sequence[Tuple[SSHConnection, int]], term: str) -> Table:
    table = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold",
        pad_edge=False,
        title=f"matches for '{term}'",
        title_style="dim",
        title_justify="left",
    )
    table.add_column("SCORE", justify="right")
    table.add_column("NAME", style="bold cyan")
    table.add_column("TARGET", style="dim")
    table.add_column("TAGS", style="magenta")
    for conn, score in matches:
        color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        table.add_row(
            f"[{color}]{score}%[/{color}]",
            conn.name,
            target_text(conn),
            tag_text(conn.tags),
        )
    return table
