from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
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
            str(conn.identity_file) if conn.identity_file else "-"
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
        border_style="cyan"
    )

def format_config_preview(config_str: str) -> Syntax:
    """Format SSH config preview with syntax highlighting."""
    return Syntax(config_str, "ssh-config", theme="monokai")