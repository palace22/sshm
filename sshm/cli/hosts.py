"""Host commands: list, show, search, add, update, rename, copy, remove."""

import os
from pathlib import Path
from typing import List, Optional

import typer
from rich.prompt import Confirm, IntPrompt, Prompt

from ..models import SSHConnection
from ..ui import console
from ..ui.tables import (
    compact_list,
    connection_detail,
    connection_table,
    connection_tree,
    search_results,
)
from ..utils import validate_ssh_key
from .common import (
    HOST_ARG,
    app,
    clearable,
    complete_folder,
    complete_tag,
    get_manager,
    handle_errors,
    show_warnings,
    split_list,
)


def _warn_key(conn: SSHConnection) -> None:
    if conn.identity_file:
        valid, key_err = validate_ssh_key(conn.identity_file)
        if not valid:
            console.print(f"[yellow]Warning (identity file): {key_err}[/yellow]")


@app.command(name="list")
@handle_errors
def list_hosts(
    search: Optional[str] = typer.Option(
        None, "--search", "-s", help="Filter by substring"
    ),
    tag: List[str] = typer.Option(
        [],
        "--tag",
        "-t",
        help="Only hosts with this tag (repeatable)",
        autocompletion=complete_tag,
    ),
    folder: Optional[str] = typer.Option(
        None,
        "--folder",
        help="Only hosts in this folder ('/' = main config)",
        autocompletion=complete_folder,
    ),
    tree: bool = typer.Option(False, "--tree", help="Show hosts grouped by folder"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed view"),
    output_format: str = typer.Option(
        "table", "--format", help="Output format: table, json, compact"
    ),
    page: int = typer.Option(1, help="Page number for pagination"),
    per_page: int = typer.Option(
        0, help="Items per page (0 = auto from terminal height)"
    ),
    all_pages: bool = typer.Option(
        False, "--all", "-a", help="Show all connections without pagination"
    ),
) -> None:
    """List SSH connections."""
    manager = get_manager()
    connections = manager.list_connections(search, tags=tag, folder=folder)
    show_warnings(manager)

    if tree:
        folders = manager.folders() if not (search or tag) else []
        console.print(
            connection_tree(connections, folders, str(manager.config.config_file))
        )
        return

    if not connections:
        console.print("[yellow]No SSH connections found.[/yellow]")
        return

    if output_format.lower() == "json":
        console.print_json(data=[c.model_dump(mode="json") for c in connections])
        return
    if output_format.lower() == "compact":
        console.print(compact_list(connections))
        console.print(f"\n[dim]Total: {len(connections)} connections[/dim]")
        return
    if detailed:
        for conn in connections:
            console.print(connection_detail(conn))
        return

    if per_page == 0:
        per_page = max(5, console.size.height - 8)
    if all_pages or len(connections) <= per_page:
        console.print(connection_table(connections))
        console.print(f"[dim]Total: {len(connections)} connections[/dim]")
        return

    total_pages = (len(connections) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    console.print(connection_table(connections[start : start + per_page]))
    console.print(
        f"[dim]Page {page} of {total_pages} | Showing {start + 1}-"
        f"{min(start + per_page, len(connections))} of {len(connections)} "
        "connections (--all to show everything)[/dim]"
    )
    hints = []
    if page > 1:
        hints.append(f"sshm list --page {page - 1}")
    if page < total_pages:
        hints.append(f"sshm list --page {page + 1}")
    console.print(f"[dim]Navigation: {' | '.join(hints)}[/dim]")


@app.command()
@handle_errors
def show(
    name: str = HOST_ARG,
    raw: bool = typer.Option(False, "--raw", help="Print the block as written"),
) -> None:
    """Show details of an SSH connection."""
    manager = get_manager()
    if raw:
        console.print(manager.raw_block(name), markup=False, highlight=False)
    else:
        console.print(connection_detail(manager.get_connection(name)))


@app.command()
@handle_errors
def search(
    query: str = typer.Argument(..., help="Search term"),
    limit: int = typer.Option(10, help="Maximum number of results"),
    min_score: int = typer.Option(40, help="Minimum fuzzy match score (0-100)"),
) -> None:
    """Fuzzy-search connections by name, alias, user, hostname and tags."""
    matches = [
        (conn, score)
        for conn, score in get_manager().find_best_matches(query, limit=limit)
        if score >= min_score
    ]
    if not matches:
        console.print(
            f"[yellow]No good matches for '{query}' (min score: {min_score})[/yellow]"
        )
        return
    console.print(search_results(matches, query))
    console.print(f"[dim]Try: sshm connect {matches[0][0].name}[/dim]")


@app.command()
@handle_errors
def add(
    name: Optional[str] = typer.Option(None, help="Connection name"),
    hostname: Optional[str] = typer.Option(None, help="Remote hostname"),
    user: Optional[str] = typer.Option(None, help="SSH username"),
    port: Optional[int] = typer.Option(None, help="SSH port"),
    identity_file: Optional[Path] = typer.Option(None, help="SSH identity file"),
    proxy_jump: Optional[str] = typer.Option(None, help="Proxy jump host"),
    local_forward: Optional[str] = typer.Option(None, help="Local port forwarding"),
    tag: List[str] = typer.Option(
        [], "--tag", "-t", help="Tag (repeatable)", autocompletion=complete_tag
    ),
    folder: Optional[str] = typer.Option(
        None, help="Folder to store the host in", autocompletion=complete_folder
    ),
) -> None:
    """Add a new SSH connection (interactive when name/hostname/user are missing)."""
    manager = get_manager()
    tags = [t for value in tag for t in split_list(value)]

    if not all([name, hostname, user]):
        console.print("[cyan]Adding new SSH connection[/cyan]")
        name = name or Prompt.ask("Connection name")
        hostname = hostname or Prompt.ask("Hostname")
        user = user or Prompt.ask("Username", default=os.getenv("USER", "root"))
        port = IntPrompt.ask("Port", default=port or 22)

        if Confirm.ask("Add identity file?", default=False):
            default_key = manager.config.default_key or "~/.ssh/id_ed25519"
            identity_file = Path(
                Prompt.ask("Identity file path", default=str(default_key))
            )
        if Confirm.ask("Add proxy jump?", default=False):
            proxy_jump = Prompt.ask("Proxy jump host")
        if Confirm.ask("Add local port forwarding?", default=False):
            local_forward = Prompt.ask("Local forward (e.g. 8080:localhost:80)")
        tags = tags or split_list(Prompt.ask("Tags (comma separated)", default=""))
        folder = folder or Prompt.ask("Folder (empty = main config)", default="")

    if not name or not hostname:
        raise ValueError("Name and hostname are required")
    connection = SSHConnection(
        name=name,
        hostname=hostname,
        user=user,
        port=port or 22,
        identity_file=identity_file,
        proxy_jump=proxy_jump,
        local_forward=local_forward,
        tags=tags,
        folder=folder or None,
    )
    _warn_key(connection)
    manager.add_connection(connection)
    show_warnings(manager)
    console.print(f"[green]Added '{connection.name}'[/green]")
    console.print(connection_detail(manager.get_connection(connection.name)))


@app.command()
@handle_errors
def update(
    name: str = HOST_ARG,
    new_name: Optional[str] = typer.Option(None, "--new-name", help="Rename the host"),
    hostname: Optional[str] = typer.Option(None, help="New hostname"),
    user: Optional[str] = typer.Option(None, help="New username ('-' to clear)"),
    port: Optional[int] = typer.Option(None, help="New port"),
    identity_file: Optional[str] = typer.Option(
        None, help="New identity file ('-' to clear)"
    ),
    proxy_jump: Optional[str] = typer.Option(
        None, help="New proxy jump host ('-' to clear)"
    ),
    local_forward: Optional[str] = typer.Option(
        None, help="New local port forwarding ('-' to clear)"
    ),
) -> None:
    """Update fields of an existing SSH connection (interactive without options)."""
    manager = get_manager()
    conn = manager.get_connection(name)

    given = [new_name, hostname, user, port, identity_file, proxy_jump, local_forward]
    if all(v is None for v in given):
        console.print(connection_detail(conn))
        console.print("[dim]Press enter to keep a value, '-' to clear it.[/dim]")
        new_name = Prompt.ask("Name", default=conn.name)
        hostname = Prompt.ask("Hostname", default=conn.hostname)
        user = Prompt.ask("User", default=conn.user or "-")
        port = IntPrompt.ask("Port", default=conn.port)
        identity_file = Prompt.ask(
            "Identity file", default=str(conn.identity_file or "-")
        )
        proxy_jump = Prompt.ask("Proxy jump", default=conn.proxy_jump or "-")
        local_forward = Prompt.ask("Local forward", default=conn.local_forward or "-")

    key = clearable(identity_file, str(conn.identity_file or "") or None)
    updated = SSHConnection(
        **{
            **conn.model_dump(),
            "name": new_name or conn.name,
            "hostname": hostname or conn.hostname,
            "user": clearable(user, conn.user),
            "port": port or conn.port,
            "identity_file": Path(key) if key else None,
            "proxy_jump": clearable(proxy_jump, conn.proxy_jump),
            "local_forward": clearable(local_forward, conn.local_forward),
        }
    )
    _warn_key(updated)
    manager.update_connection(name, updated)
    show_warnings(manager)
    console.print(f"[green]Updated '{updated.name}'[/green]")
    console.print(connection_detail(manager.get_connection(updated.name)))


@app.command()
@handle_errors
def rename(
    name: str = HOST_ARG,
    new_name: str = typer.Argument(..., help="New name"),
) -> None:
    """Rename a host or one of its aliases (ProxyJump references follow)."""
    manager = get_manager()
    updated = manager.rename_connection(name, new_name)
    show_warnings(manager)
    console.print(f"[green]Renamed '{name}' -> '{new_name}'[/green]")
    if updated:
        console.print(f"[dim]Updated ProxyJump in: {', '.join(updated)}[/dim]")


@app.command()
@handle_errors
def copy(
    source: str = HOST_ARG,
    new_name: str = typer.Argument(..., help="Name for the new connection"),
) -> None:
    """Clone a host under a new name, with all its options and comments."""
    manager = get_manager()
    manager.copy_connection(source, new_name)
    show_warnings(manager)
    console.print(f"[green]Copied '{source}' -> '{new_name}'[/green]")
    console.print(connection_detail(manager.get_connection(new_name)))


@app.command()
@handle_errors
def remove(
    name: str = HOST_ARG,
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove an SSH connection."""
    manager = get_manager()
    conn = manager.get_connection(name)

    if not force:
        console.print(connection_detail(conn))
        referrers = manager.referrers(conn.name)
        if referrers:
            console.print(
                f"[yellow]Used as ProxyJump by: {', '.join(referrers)}[/yellow]"
            )
        if not Confirm.ask(f"Remove '{conn.name}'?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    manager.remove_connection(name)
    show_warnings(manager)
    console.print(f"[green]Removed '{conn.name}'[/green]")
