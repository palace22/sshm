import typer
from typing import Optional
from pathlib import Path
from rich.prompt import Prompt, Confirm
import subprocess
import sys
import json

from .models import SSHConnection, AppConfig
from .manager import SSHManager
from .formatters import (
    console,
    format_connection_table,
    format_connection_detail,
    format_config_preview
)

app = typer.Typer(
    help="SSH Manager - A modern CLI tool to manage SSH connections",
    no_args_is_help=True
)

def get_manager() -> SSHManager:
    """Get an instance of SSHManager with default config."""
    config = AppConfig()
    return SSHManager(config)

@app.command()
def list(
    search: Optional[str] = typer.Option(None, help="Filter connections by name"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed view"),
    format: str = typer.Option("table", help="Output format: table, json")
):
    """List all SSH connections."""
    manager = get_manager()
    connections = manager.list_connections(search)
    
    if not connections:
        console.print("[yellow]No SSH connections found.[/yellow]")
        return
    
    if format.lower() == "json":
        console.print_json(data=[conn.model_dump() for conn in connections])
    elif detailed:
        for conn in connections:
            console.print(format_connection_detail(conn))
    else:
        console.print(format_connection_table(connections))

@app.command()
def add(
    name: Optional[str] = typer.Option(None, help="Connection name"),
    hostname: Optional[str] = typer.Option(None, help="Remote hostname"),
    user: Optional[str] = typer.Option(None, help="SSH username"),
    port: Optional[int] = typer.Option(None, help="SSH port"),
    identity_file: Optional[Path] = typer.Option(None, help="SSH identity file"),
):
    """Add a new SSH connection."""
    manager = get_manager()
    
    # Interactive mode if no arguments provided
    if not all([name, hostname, user]):
        name = name or Prompt.ask("Connection name")
        hostname = hostname or Prompt.ask("Hostname")
        user = user or Prompt.ask("Username")
        port = port or int(Prompt.ask("Port", default="22"))
        identity_file = identity_file or Path(
            Prompt.ask("Identity file", default="~/.ssh/id_rsa")
        ).expanduser()

    connection = SSHConnection(
        name=name,
        hostname=hostname,
        user=user,
        port=port or 22,
        identity_file=identity_file
    )

    try:
        manager.add_connection(connection)
        console.print(f"[green]Successfully added connection '{name}'[/green]")
        console.print(format_connection_detail(connection))
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

@app.command()
def update(
    name: str = typer.Argument(..., help="Connection name to update"),
    hostname: Optional[str] = typer.Option(None, help="New hostname"),
    user: Optional[str] = typer.Option(None, help="New username"),
    port: Optional[int] = typer.Option(None, help="New port"),
    identity_file: Optional[Path] = typer.Option(None, help="New identity file"),
):
    """Update an existing SSH connection."""
    manager = get_manager()
    
    try:
        connection = manager.get_connection(name)
        
        # Interactive mode if no options provided
        if not any([hostname, user, port, identity_file]):
            console.print(format_connection_detail(connection))
            if Prompt.ask("Update hostname?", default="n") == "y":
                hostname = Prompt.ask("New hostname", default=connection.hostname)
            if Prompt.ask("Update username?", default="n") == "y":
                user = Prompt.ask("New username", default=connection.user)
            if Prompt.ask("Update port?", default="n") == "y":
                port = int(Prompt.ask("New port", default=str(connection.port)))
            if Prompt.ask("Update identity file?", default="n") == "y":
                identity_file = Path(
                    Prompt.ask("New identity file", default=str(connection.identity_file or "~/.ssh/id_rsa"))
                ).expanduser()

        # Update connection with new values
        updated_connection = SSHConnection(
            name=name,
            hostname=hostname or connection.hostname,
            user=user or connection.user,
            port=port or connection.port,
            identity_file=identity_file or connection.identity_file,
            extra_options=connection.extra_options
        )

        manager.update_connection(name, updated_connection)
        console.print(f"[green]Successfully updated connection '{name}'[/green]")
        console.print(format_connection_detail(updated_connection))
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

@app.command()
def remove(
    name: str = typer.Argument(..., help="Connection name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove an SSH connection."""
    manager = get_manager()
    
    try:
        connection = manager.get_connection(name)
        console.print(format_connection_detail(connection))
        
        if not force and not Confirm.ask(
            f"Are you sure you want to remove connection '{name}'?",
            default=False
        ):
            console.print("[yellow]Operation cancelled.[/yellow]")
            return
            
        manager.remove_connection(name)
        console.print(f"[green]Successfully removed connection '{name}'[/green]")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

@app.command()
def connect(
    name: str = typer.Argument(..., help="Connection name to connect to"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show command without executing"),
):
    """Connect to a host using SSH."""
    manager = get_manager()
    
    try:
        connection = manager.get_connection(name)
        
        # Build SSH command
        cmd = ["ssh"]
        if connection.identity_file:
            cmd.extend(["-i", str(connection.identity_file)])
        if connection.port != 22:
            cmd.extend(["-p", str(connection.port)])
        cmd.append(f"{connection.user}@{connection.hostname}")
        
        if dry_run:
            console.print("[cyan]Command:[/cyan] " + " ".join(cmd))
            return
            
        console.print(f"[green]Connecting to '{name}'...[/green]")
        subprocess.run(cmd)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        sys.exit(1)

@app.command()
def config(
    action: str = typer.Argument(..., help="Action to perform: get, set"),
    key: Optional[str] = typer.Argument(None, help="Config key to get/set"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
):
    """Manage SSH Manager configuration."""
    if action not in ["get", "set"]:
        console.print("[red]Invalid action. Use 'get' or 'set'[/red]")
        sys.exit(1)
        
    config = AppConfig()
    
    if action == "get":
        if key:
            if hasattr(config, key):
                console.print(f"{key}: {getattr(config, key)}")
            else:
                console.print(f"[red]Unknown config key: {key}[/red]")
                sys.exit(1)
        else:
            console.print_json(config.model_dump())
    else:  # set
        if not key or not value:
            console.print("[red]Both key and value are required for 'set'[/red]")
            sys.exit(1)
            
        if not hasattr(config, key):
            console.print(f"[red]Unknown config key: {key}[/red]")
            sys.exit(1)
            
        setattr(config, key, value)
        # Save configuration
        config_file = Path.home() / ".ssh-manager" / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(config.model_dump(), indent=2))
        console.print(f"[green]Successfully updated {key}[/green]")

def main():
    """Entry point for the CLI."""
    app()

if __name__ == "__main__":
    main()