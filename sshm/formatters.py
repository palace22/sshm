from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import List
from .models import SSHConnection

console = Console()


def format_connection_table(connections: List[SSHConnection]) -> Table:
    """Format SSH connections as a beautiful table."""
    table = Table(title="SSH Connections")

    table.add_column("Name", style="cyan")
    table.add_column("Hostname", style="green")
    table.add_column("User", style="yellow")
    table.add_column("Port", style="magenta")
    table.add_column("Identity File", style="blue")

    for conn in connections:
        table.add_row(
            conn.name,
            conn.hostname,
            conn.user,
            str(conn.port),
            str(conn.identity_file) if conn.identity_file else "-",
        )

    return table


def format_connection_detail(connection: SSHConnection) -> Panel:
    """Format a single SSH connection as a detailed panel."""
    content = [
        f"[cyan]Name:[/cyan] {connection.name}",
        f"[green]Hostname:[/green] {connection.hostname}",
        f"[yellow]User:[/yellow] {connection.user}",
        f"[magenta]Port:[/magenta] {connection.port}",
    ]

    if connection.identity_file:
        content.append(f"[blue]Identity File:[/blue] {connection.identity_file}")

    if connection.extra_options:
        content.append("\n[white]Extra Options:[/white]")
        for key, value in connection.extra_options.items():
            content.append(f"  [dim]{key}:[/dim] {value}")

    return Panel(
        "\n".join(content),
        title=f"SSH Connection: {connection.name}",
        border_style="cyan",
    )


def format_config_preview(config_str: str) -> Syntax:
    """Format SSH config preview with syntax highlighting."""
    return Syntax(config_str, "ssh-config", theme="monokai")


def format_paginated_table(
    connections: List[SSHConnection], page: int = 1, per_page: int = 10
) -> tuple[Table, dict]:
    """Format connections in a paginated table with navigation info."""
    total = len(connections)
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total)

    # Get connections for current page
    page_connections = connections[start_idx:end_idx]

    # Create table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Name", style="cyan", width=20)
    table.add_column("Hostname", style="green", width=25)
    table.add_column("User", style="yellow", width=15)
    table.add_column("Port", justify="center", width=6)
    table.add_column("Key", style="blue", width=20)

    for connection in page_connections:
        key_display = (
            str(connection.identity_file.name)
            if connection.identity_file
            else "default"
        )
        if len(key_display) > 18:
            key_display = key_display[:15] + "..."

        table.add_row(
            connection.name,
            connection.hostname,
            connection.user,
            str(connection.port),
            key_display,
        )

    # Navigation info
    total_pages = (total + per_page - 1) // per_page
    nav_info = {
        "current_page": page,
        "total_pages": total_pages,
        "total_items": total,
        "showing_start": start_idx + 1 if total > 0 else 0,
        "showing_end": end_idx,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

    return table, nav_info


def format_compact_list(connections: List[SSHConnection], columns: int = 3) -> Columns:
    """Format connections in a compact column layout."""
    items = []
    for conn in connections:
        item = f"[cyan]{conn.name}[/cyan]\n[dim]{conn.user}@{conn.hostname}[/dim]"
        items.append(Panel(item, border_style="dim", padding=(0, 1)))

    return Columns(items, equal=True, expand=True)


def format_search_suggestions(matches: List[tuple], search_term: str) -> Panel:
    """Format fuzzy search suggestions with scores."""
    if not matches:
        return Panel("No matches found", title="Search Results", border_style="red")

    content = []
    content.append(f"[yellow]Search term:[/yellow] '{search_term}'\n")

    for i, (connection, score) in enumerate(matches, 1):
        score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        content.append(
            f"{i}. [cyan]{connection.name}[/cyan] [{score_color}]({score}%)[/{score_color}]"
        )
        content.append(
            f"   [dim]{connection.user}@{connection.hostname}:{connection.port}[/dim]"
        )
        if i < len(matches):
            content.append("")

    return Panel("\n".join(content), title="Did you mean?", border_style="yellow")
