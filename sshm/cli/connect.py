"""Connecting: the bare ``sshm`` picker, ``connect``, ``open`` (tabs) and ``test``."""

import shlex
import subprocess
from typing import List, Optional

import typer
from rich.text import Text

from .. import __version__
from ..manager import SSHManager
from ..models import SSHConnection
from ..tabs import Tab, in_tab, rename_current
from ..ui import console, effects, picker
from ..ui.tables import target_text
from ..utils import check_tcp_port
from .common import (
    HOST_ARG,
    app,
    choose,
    complete_host,
    get_history,
    get_manager,
    get_tabs,
    handle_errors,
    run_ssh,
    show_warnings,
)


def _connect(
    manager: SSHManager,
    conn: SSHConnection,
    extra_args: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Replace this process with ssh to one host."""
    if conn.identity_file and not conn.identity_file.exists():
        console.print(
            f"[yellow]Warning: Identity file {conn.identity_file} not found[/yellow]"
        )

    cmd = manager.ssh_command(conn, extra_args=extra_args)
    if dry_run:
        console.print("[cyan]SSH Command:[/cyan]")
        console.print(shlex.join(cmd), markup=False, highlight=False, soft_wrap=True)
        return

    get_history().record(conn.name)
    if in_tab():
        rename_current(conn.name)  # the "new" tab becomes this host's tab
    line = Text.assemble(
        (">> ", "bold cyan"), (conn.name, "bold"), "  ", (target_text(conn), "dim")
    )
    if conn.proxy_jump:
        line.append(f"  via {conn.proxy_jump}", style="dim")
    effects.typewriter(console, line)
    console.print(f"[dim]$ {shlex.join(cmd)}[/dim]", highlight=False, soft_wrap=True)
    run_ssh(cmd)


def _open_tabs(
    manager: SSHManager,
    conns: List[SSHConnection],
    extra_args: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Open one tab per host (attaching to the tab session when needed)."""
    tabs = [Tab(c.name, manager.ssh_command(c, extra_args=extra_args)) for c in conns]
    if dry_run:
        for tab in tabs:
            console.print(
                f"[cyan]{tab.name}:[/cyan] {shlex.join(tab.command)}",
                highlight=False,
                soft_wrap=True,
            )
        return

    history = get_history()
    for conn in conns:
        history.record(conn.name)
    session = get_tabs()
    if session.open(tabs):
        session.attach()
    console.print(f"[green]Opened {len(tabs)} tabs[/green]")


def _go(
    manager: SSHManager,
    conns: List[SSHConnection],
    extra_args: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """One host: connect here. Several: open them as tabs."""
    if len(conns) == 1:
        _connect(manager, conns[0], extra_args, dry_run)
    else:
        _open_tabs(manager, conns, extra_args, dry_run)


def _resolve(
    manager: SSHManager, name: Optional[str], fuzzy: bool = True
) -> List[SSHConnection]:
    """Exact name/alias, else a single strong fuzzy match, else ask the user."""
    connections = get_history().sort(manager.list_connections())
    if not connections:
        raise ValueError("No SSH connections found. Add one with 'sshm add'.")

    query = name or ""
    if name and not name.startswith(("@", "/")):
        try:
            return [manager.get_connection(name)]
        except ValueError:
            if not fuzzy:
                raise
        strong = [c for c, s in manager.find_best_matches(name, 20) if s >= 90]
        if len(strong) == 1:
            console.print(f"[dim]'{name}' -> '{strong[0].name}'[/dim]")
            return strong

    candidates = picker.filter_connections(connections, query, manager.score)
    if not candidates:
        raise ValueError(f"No connection found matching '{name}'")
    title = "new tab" if in_tab() else ""
    chosen = choose(
        connections if picker.supported() else candidates, manager, query, title
    )
    if not chosen:
        raise typer.Exit(0)
    return chosen


def _welcome() -> None:
    """What a bare `sshm` shows when there is nothing to pick from."""
    effects.banner(console, __version__)
    console.print()
    console.print("  No hosts yet. Add one, or check which file sshm manages:\n")
    for command, meaning in [
        ("sshm add", "add a host interactively"),
        ("sshm config show", "settings (config_file = the ssh config in use)"),
        ("sshm --help", "all commands"),
        ("sshm man", "the manual"),
    ]:
        console.print(f"    [cyan]{command:<18}[/cyan] [dim]{meaning}[/dim]")


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show the version and exit"
    ),
) -> None:
    """Without a command: open the interactive host picker."""
    if version:
        effects.banner(console, __version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    if not picker.supported():
        console.print(ctx.get_help())
        raise typer.Exit()
    _pick_and_go()


@handle_errors
def _pick_and_go() -> None:
    manager = get_manager()
    show_warnings(manager)
    if not manager.list_connections():
        _welcome()
        return
    _go(manager, _resolve(manager, None))


@app.command()
@handle_errors
def connect(
    name: Optional[str] = typer.Argument(
        None,
        help="Host name or alias; '@tag' or '/folder' opens a filtered picker. "
        "Omit to pick interactively.",
        autocompletion=complete_host,
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ssh command"),
    extra_args: Optional[str] = typer.Option(None, help="Extra SSH arguments"),
    fuzzy: bool = typer.Option(
        True, "--fuzzy/--no-fuzzy", help="Fall back to fuzzy matching"
    ),
) -> None:
    """Connect to a host (mark several in the picker with tab to open tabs)."""
    manager = get_manager()
    _go(manager, _resolve(manager, name, fuzzy), extra_args, dry_run)


@app.command(name="open")
@handle_errors
def open_tabs(
    targets: Optional[List[str]] = typer.Argument(
        None,
        help="Hosts, '@tag' or '/folder' (all matching hosts). Omit to pick.",
        autocompletion=complete_host,
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ssh commands"),
    extra_args: Optional[str] = typer.Option(None, help="Extra SSH arguments"),
) -> None:
    """Open hosts as tabs: click or alt-left/right to switch (needs tmux)."""
    manager = get_manager()
    if not targets:
        conns = _resolve(manager, None)
    else:
        everything = manager.list_connections()
        conns = []
        for target in targets:
            if target.startswith(("@", "/")):
                found = picker.filter_connections(everything, target, manager.score)
                if not found:
                    raise ValueError(f"No hosts match '{target}'")
                conns += found
            else:
                conns.append(manager.get_connection(target))
    unique = list({c.name: c for c in conns}.values())
    _open_tabs(manager, unique, extra_args, dry_run)


@app.command()
@handle_errors
def tabs(
    close: bool = typer.Option(False, "--close", help="Close every tab"),
) -> None:
    """Return to the open tabs (they keep running after alt-d detach)."""
    session = get_tabs()
    session.check()
    if not session.exists():
        console.print(
            "[yellow]No open tabs.[/yellow] [dim]Start some with: "
            "sshm open HOST... | sshm open @tag | sshm (tab to mark, enter)[/dim]"
        )
        return
    if close:
        session.close()
        console.print("[green]Closed all tabs[/green]")
        return
    console.print(f"[dim]tabs: {', '.join(session.windows())}[/dim]")
    session.attach()


@app.command()
@handle_errors
def test(
    name: str = HOST_ARG,
    timeout: int = typer.Option(10, help="Connection timeout in seconds"),
) -> None:
    """Check that a host is reachable and accepts key-based login."""
    manager = get_manager()
    conn = manager.get_connection(name)

    # A direct TCP probe is meaningless when ssh reaches the host through a
    # jump host or proxy command.
    proxied = conn.proxy_jump or any(
        k.lower() == "proxycommand" for k in conn.extra_options
    )
    if not proxied:
        with effects.spinner(console, f"tcp {conn.hostname}:{conn.port}"):
            reachable, reach_err = check_tcp_port(conn.hostname, conn.port, timeout)
        if not reachable:
            effects.fail(console, f"tcp    {reach_err}")
            raise typer.Exit(1)
        effects.ok(console, f"tcp    {conn.hostname}:{conn.port}")

    cmd = manager.ssh_command(
        conn,
        options=["BatchMode=yes", f"ConnectTimeout={timeout}"],
        remote_command=["exit"],
    )
    with effects.spinner(console, f"ssh {conn.name}"):
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        effects.fail(console, f"ssh    {conn.name}")
        if result.stderr:
            console.print(f"[dim]{result.stderr.strip()}[/dim]", highlight=False)
        console.print(f"[dim]$ {shlex.join(cmd)}[/dim]", highlight=False)
        raise typer.Exit(1)
    effects.ok(console, f"ssh    {conn.name} accepts key-based login")
