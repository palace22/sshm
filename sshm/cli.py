import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.prompt import Confirm, Prompt

from .config import ConfigManager
from .formatters import (
    console,
    format_compact_list,
    format_connection_detail,
    format_connection_table,
    format_paginated_table,
    format_search_suggestions,
)
from .manager import SSHManager
from .models import SSHConnection

app = typer.Typer(
    help="SSH Manager - A modern CLI tool to manage SSH connections",
    no_args_is_help=True,
)


def connection_name_completion(incomplete: str) -> list[str]:
    """Provide completion suggestions for connection names with fuzzy matching."""
    try:
        manager = get_manager()
        connections = manager.list_connections()

        if not incomplete:
            # If no input, return all connection names
            return [conn.name for conn in connections]

        # First try exact prefix matching (for better performance)
        prefix_matches = [
            conn.name for conn in connections if conn.name.startswith(incomplete)
        ]
        if prefix_matches:
            return prefix_matches

        # If no prefix matches, use fuzzy matching and return ALL results
        # This allows the shell to handle the filtering
        matches = manager.find_best_matches(incomplete, limit=50)
        # Filter by minimum score of 30 and return all matches
        filtered_matches = [match[0].name for match in matches if match[1] >= 30]

        # Return all fuzzy matches - the shell will filter them
        return filtered_matches

    except Exception:
        # Fallback to empty list if there's any error
        return []


def get_manager() -> SSHManager:
    """Get an instance of SSHManager with loaded config."""
    config_manager = ConfigManager()
    config = config_manager.load_config()
    return SSHManager(config)


@app.command()
def list(
    search: Optional[str] = typer.Option(None, help="Filter connections by name"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed view"),
    format: str = typer.Option("table", help="Output format: table, json, compact"),
    page: int = typer.Option(1, "--page", "-p", help="Page number for pagination"),
    per_page: int = typer.Option(10, "--per-page", help="Items per page"),
    all_pages: bool = typer.Option(
        False, "--all", "-a", help="Show all connections without pagination"
    ),
) -> None:
    """List all SSH connections."""
    try:
        manager = get_manager()
        connections = manager.list_connections(search)

        if not connections:
            if search:
                console.print(
                    f"[yellow]No SSH connections found matching '{search}'.[/yellow]"
                )
            else:
                console.print("[yellow]No SSH connections found.[/yellow]")
            return

        if format.lower() == "json":
            console.print_json(data=[conn.model_dump() for conn in connections])
            return

        if format.lower() == "compact":
            console.print(format_compact_list(connections))
            console.print(f"\n[dim]Total: {len(connections)} connections[/dim]")
            return

        if detailed:
            for conn in connections:
                console.print(format_connection_detail(conn))
                console.print()  # Add spacing between connections
            return

        # Paginated table view
        if all_pages or len(connections) <= per_page:
            console.print(format_connection_table(connections))
            console.print(f"\n[dim]Total: {len(connections)} connections[/dim]")
        else:
            table, nav_info = format_paginated_table(connections, page, per_page)
            console.print(table)

            # Show pagination info
            nav_text = (
                f"[dim]Page {nav_info['current_page']} of {nav_info['total_pages']} | "
                f"Showing {nav_info['showing_start']}-{nav_info['showing_end']} "
                f"of {nav_info['total_items']} connections[/dim]"
            )
            console.print(f"\n{nav_text}")

            # Show navigation hints
            hints = []
            if nav_info["has_prev"]:
                hints.append(f"sshm list --page {page - 1}")
            if nav_info["has_next"]:
                hints.append(f"sshm list --page {page + 1}")
            if hints:
                console.print(f"[dim]Navigation: {' | '.join(hints)}[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def add(
    name: Optional[str] = typer.Option(None, help="Connection name"),
    hostname: Optional[str] = typer.Option(None, help="Remote hostname"),
    user: Optional[str] = typer.Option(None, help="SSH username"),
    port: Optional[int] = typer.Option(None, help="SSH port"),
    identity_file: Optional[Path] = typer.Option(None, help="SSH identity file"),
) -> None:
    """Add a new SSH connection."""
    try:
        manager = get_manager()

        # Interactive mode if no arguments provided
        if not all([name, hostname, user]):
            console.print("[cyan]Adding new SSH connection[/cyan]")
            name = name or Prompt.ask("Connection name")
            hostname = hostname or Prompt.ask("Hostname")
            user = user or Prompt.ask("Username", default=os.getenv("USER", "root"))

            port_str = Prompt.ask("Port", default="22")
            try:
                port = int(port_str)
            except ValueError:
                port = 22

            if Confirm.ask("Add identity file?", default=False):
                identity_file_str = Prompt.ask(
                    "Identity file path", default="~/.ssh/id_rsa"
                )
                identity_file = Path(identity_file_str).expanduser()
            else:
                identity_file = None

        connection = SSHConnection(
            name=name,
            hostname=hostname,
            user=user,
            port=port or 22,
            identity_file=identity_file,
        )

        manager.add_connection(connection)
        console.print(f"[green]Successfully added connection '{name}'[/green]")
        console.print(format_connection_detail(connection))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def update(
    name: str = typer.Argument(
        ..., help="Connection name to update", autocompletion=connection_name_completion
    ),
    hostname: Optional[str] = typer.Option(None, help="New hostname"),
    user: Optional[str] = typer.Option(None, help="New username"),
    port: Optional[int] = typer.Option(None, help="New port"),
    identity_file: Optional[Path] = typer.Option(None, help="New identity file"),
) -> None:
    """Update an existing SSH connection."""
    try:
        manager = get_manager()
        connection = manager.get_connection(name)

        # Interactive mode if no options provided
        if not any([hostname, user, port, identity_file]):
            console.print("[cyan]Updating SSH connection[/cyan]")
            console.print(format_connection_detail(connection))
            console.print()

            if Prompt.ask("Update hostname?", default="n").lower() == "y":
                hostname = Prompt.ask("New hostname", default=connection.hostname)
            if Prompt.ask("Update username?", default="n").lower() == "y":
                user = Prompt.ask("New username", default=connection.user)
            if Prompt.ask("Update port?", default="n").lower() == "y":
                port_str = Prompt.ask("New port", default=str(connection.port))
                try:
                    port = int(port_str)
                except ValueError:
                    port = connection.port
            if Prompt.ask("Update identity file?", default="n").lower() == "y":
                identity_file_str = Prompt.ask(
                    "New identity file",
                    default=str(connection.identity_file or "~/.ssh/id_rsa"),
                )
                identity_file = Path(identity_file_str).expanduser()

        # Update connection with new values
        updated_connection = SSHConnection(
            name=name,
            hostname=hostname or connection.hostname,
            user=user or connection.user,
            port=port or connection.port,
            identity_file=identity_file or connection.identity_file,
            extra_options=connection.extra_options,
        )

        manager.update_connection(name, updated_connection)
        console.print(f"[green]Successfully updated connection '{name}'[/green]")
        console.print(format_connection_detail(updated_connection))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def remove(
    name: str = typer.Argument(
        ..., help="Connection name to remove", autocompletion=connection_name_completion
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove an SSH connection."""
    try:
        manager = get_manager()
        connection = manager.get_connection(name)

        if not force:
            console.print("[yellow]Connection to be removed:[/yellow]")
            console.print(format_connection_detail(connection))
            console.print()

            if not Confirm.ask(
                f"Are you sure you want to remove connection '{name}'?", default=False
            ):
                console.print("[yellow]Operation cancelled.[/yellow]")
                return

        manager.remove_connection(name)
        console.print(f"[green]Successfully removed connection '{name}'[/green]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def connect(
    name: str = typer.Argument(
        ...,
        help="Connection name to connect to",
        autocompletion=connection_name_completion,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show command without executing"
    ),
    extra_args: Optional[str] = typer.Option(None, help="Extra SSH arguments"),
    fuzzy: bool = typer.Option(
        True, "--fuzzy/--no-fuzzy", help="Enable fuzzy search for connection names"
    ),
) -> None:
    """Connect to a host using SSH."""
    try:
        manager = get_manager()

        # Try exact match first
        try:
            connection = manager.get_connection(name)
        except ValueError:
            # If exact match fails and fuzzy search is enabled, try fuzzy search
            if fuzzy:
                # Get all matching suggestions ranked by score
                suggestions = manager.find_best_matches(name, limit=20)

                if not suggestions:
                    console.print(f"[red]No connection found matching '{name}'[/red]")
                    sys.exit(1)

                # Check if we should auto-connect: only if exactly ONE match
                # has 90+ score
                high_score_matches = [s for s in suggestions if s[1] >= 90]

                if len(high_score_matches) == 1:
                    # Exactly one high-confidence match - auto-connect
                    best_match = high_score_matches[0]
                    console.print(
                        "[yellow]Exact match not found. Using best match:[/yellow]"
                    )
                    console.print(
                        f"[cyan]'{name}' → '{best_match[0].name}' "
                        f"({best_match[1]}% match)[/cyan]"
                    )
                    connection = best_match[0]
                else:
                    # Show all suggestions and let user choose
                    console.print(
                        f"[yellow]Multiple matches found for '{name}':[/yellow]\n"
                    )

                    # Display suggestions with numbers
                    suggestions = (
                        suggestions
                        if len(high_score_matches) == 0
                        else high_score_matches
                    )
                    for i, (conn, score) in enumerate(
                        suggestions,
                        1,
                    ):
                        score_color = (
                            "green"
                            if score >= 80
                            else "yellow" if score >= 60 else "red"
                        )
                        console.print(
                            f"[bold]{i:2}.[/bold] [cyan]{conn.name}[/cyan] "
                            f"[{score_color}]({score}%)[/{score_color}] "
                            f"[dim]{conn.user}@{conn.hostname}[/dim]"
                        )

                    console.print("\n[bold]0.[/bold] [red]Cancel[/red]")

                    # Get user choice
                    try:
                        choice = Prompt.ask(
                            "\nSelect connection to connect to",
                            choices=[str(i) for i in range(len(suggestions) + 1)],
                            default="1",
                        )
                        choice_num = int(choice)

                        if choice_num == 0:
                            console.print("[yellow]Connection cancelled.[/yellow]")
                            sys.exit(0)
                        elif 1 <= choice_num <= len(suggestions):
                            connection = suggestions[choice_num - 1][0]
                            console.print(
                                f"[green]Connecting to '{connection.name}'...[/green]"
                            )
                        else:
                            console.print("[red]Invalid choice.[/red]")
                            sys.exit(1)
                    except (ValueError, KeyboardInterrupt):
                        console.print("\n[yellow]Connection cancelled.[/yellow]")
                        sys.exit(0)
            else:
                raise

        # Build SSH command
        cmd = ["ssh"]

        # Add identity file if specified
        if connection.identity_file and connection.identity_file.exists():
            cmd.extend(["-i", str(connection.identity_file)])
        elif connection.identity_file:
            console.print(
                f"[yellow]Warning: Identity file {connection.identity_file} "
                f"not found[/yellow]"
            )

        # Add port if not default
        if connection.port != 22:
            cmd.extend(["-p", str(connection.port)])

        # Add extra SSH options from config
        for key, value in connection.extra_options.items():
            cmd.extend(["-o", f"{key}={value}"])

        # Add extra arguments if provided
        if extra_args:
            cmd.extend(extra_args.split())

        # Add user@hostname
        cmd.append(f"{connection.user}@{connection.hostname}")

        if dry_run:
            console.print("[cyan]SSH Command:[/cyan]")
            console.print(" ".join(cmd))
            return

        console.print(
            f"[green]Connecting to '{connection.name}' "
            f"({connection.hostname})...[/green]"
        )
        try:
            subprocess.run(cmd, check=False)
        except KeyboardInterrupt:
            console.print("\n[yellow]Connection interrupted by user[/yellow]")
        except FileNotFoundError:
            console.print(
                "[red]Error: SSH command not found. "
                "Please install OpenSSH client.[/red]"
            )
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def test(
    name: str = typer.Argument(
        ..., help="Connection name to test", autocompletion=connection_name_completion
    ),
    timeout: int = typer.Option(10, help="Connection timeout in seconds"),
) -> None:
    """Test SSH connection without connecting."""
    try:
        manager = get_manager()
        connection = manager.get_connection(name)

        console.print(f"[cyan]Testing connection to '{name}'...[/cyan]")

        # Build test command
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}"]

        if connection.identity_file and connection.identity_file.exists():
            cmd.extend(["-i", str(connection.identity_file)])

        if connection.port != 22:
            cmd.extend(["-p", str(connection.port)])

        cmd.extend([f"{connection.user}@{connection.hostname}", "exit"])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            console.print(f"[green]✓ Connection to '{name}' successful[/green]")
        else:
            console.print(f"[red]✗ Connection to '{name}' failed[/red]")
            if result.stderr:
                console.print(f"[red]Error: {result.stderr.strip()}[/red]")
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def config(
    action: str = typer.Argument(..., help="Action to perform: get, set, show"),
    key: Optional[str] = typer.Argument(None, help="Config key to get/set"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
) -> None:
    """Manage SSH Manager configuration."""
    try:
        if action not in ["get", "set", "show"]:
            console.print("[red]Invalid action. Use 'get', 'set', or 'show'[/red]")
            sys.exit(1)

        config_manager = ConfigManager()
        config = config_manager.load_config()

        if action == "show":
            console.print("[cyan]SSH Manager Configuration:[/cyan]")
            console.print(f"Config File: {config.config_file}")
            console.print(f"Backup Directory: {config.backup_dir}")
            console.print(f"Auto Backup: {config.auto_backup}")
            console.print(f"Default Key: {config.default_key or 'None'}")
            return

        if action == "get":
            if key:
                if hasattr(config, key):
                    console.print(f"{key}: {getattr(config, key)}")
                else:
                    console.print(f"[red]Unknown config key: {key}[/red]")
                    console.print(
                        "Available keys: config_file, backup_dir, "
                        "auto_backup, default_key"
                    )
                    sys.exit(1)
            else:
                console.print_json(config.model_dump())
        else:  # set
            if not key or value is None:
                console.print("[red]Both key and value are required for 'set'[/red]")
                sys.exit(1)

            try:
                config_manager.set_setting(key, value)
                console.print(f"[green]Successfully updated {key}[/green]")
            except ValueError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def export(
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file path"
    ),
    format: str = typer.Option("json", help="Export format: json, yaml"),
) -> None:
    """Export SSH connections to a file."""
    try:
        manager = get_manager()
        connections = manager.list_connections()

        if not connections:
            console.print("[yellow]No connections to export[/yellow]")
            return

        # Prepare export data
        export_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "connections": [conn.model_dump() for conn in connections],
        }

        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = Path(f"sshm_export_{timestamp}.{format}")

        if format.lower() == "json":
            output_file.write_text(json.dumps(export_data, indent=2, default=str))
        else:
            console.print(f"[red]Unsupported format: {format}[/red]")
            sys.exit(1)

        console.print(
            f"[green]Exported {len(connections)} connections to {output_file}[/green]"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@app.command()
def backup(
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Backup directory"
    ),
) -> None:
    """Create a manual backup of SSH config."""
    try:
        manager = get_manager()

        if output_dir is None:
            output_dir = manager.config.backup_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = output_dir / f"config_{timestamp}.bak"

        if manager.config.config_file.exists():
            shutil.copy2(manager.config.config_file, backup_file)
            console.print(f"[green]Backup created: {backup_file}[/green]")
        else:
            console.print("[yellow]No SSH config file found to backup[/yellow]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search term for connection names"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of results"),
    min_score: int = typer.Option(
        40, "--min-score", help="Minimum fuzzy match score (0-100)"
    ),
) -> None:
    """Search connections using fuzzy matching."""
    try:
        manager = get_manager()
        matches = manager.find_best_matches(query, limit=limit)

        if not matches:
            console.print(f"[yellow]No connections found matching '{query}'[/yellow]")
            return

        # Filter by minimum score
        filtered_matches = [
            (conn, score) for conn, score in matches if score >= min_score
        ]

        if not filtered_matches:
            console.print(
                f"[yellow]No good matches found for '{query}' (min score: {min_score})[/yellow]"
            )
            console.print(
                "[dim]Try lowering --min-score or use a different search term[/dim]"
            )
            return

        console.print(format_search_suggestions(filtered_matches, query))

        # Show usage hint
        if filtered_matches:
            best_match = filtered_matches[0][0]
            console.print(f"\n[dim]Try: sshm connect {best_match.name}[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
