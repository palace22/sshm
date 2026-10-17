"""Data commands: export, import, backup, sshm's own settings and the manual."""

import json
import os
import shutil
import subprocess
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from ..config import ConfigManager
from ..models import AppConfig, SSHConnection
from ..ui import console
from .common import app, describe_error, get_manager, handle_errors, show_warnings

EXPORT_VERSION = "1.1"
# Where `man` looks for user-installed pages (on PATH-derived manpath via ~/.local/bin).
USER_MAN_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "man"
    / "man1"
)


@app.command()
@handle_errors
def export(
    output_file: Optional[Path] = typer.Option(None, help="Output file path"),
    output_format: str = typer.Option("json", "--format", help="Export format: json"),
) -> None:
    """Export all connections (with tags and folders) to a JSON file."""
    if output_format.lower() != "json":
        raise ValueError("Only the json format is supported")
    connections = get_manager().list_connections()
    if not connections:
        console.print("[yellow]No connections to export[/yellow]")
        return

    data = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "connections": [c.model_dump(mode="json") for c in connections],
    }
    if output_file is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(f"sshm_export_{stamp}.json")
    output_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    console.print(
        f"[green]Exported {len(connections)} connections to {output_file}[/green]"
    )


@app.command(name="import")
@handle_errors
def import_connections(
    input_file: Path = typer.Argument(..., help="JSON file exported by 'sshm export'"),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing connections with the same name"
    ),
) -> None:
    """Import connections from a file written by 'sshm export' (format 1.0 or 1.1)."""
    if not input_file.exists():
        raise ValueError(f"File not found: {input_file}")
    try:
        entries = json.loads(input_file.read_text(encoding="utf-8")).get(
            "connections", []
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON file: {e}")
    if not entries:
        console.print("[yellow]No connections found in file[/yellow]")
        return

    manager = get_manager()
    existing = {c.name for c in manager.list_connections()}
    imported = overwritten = skipped = 0

    for entry in entries:
        try:
            conn = SSHConnection(
                **{k: v for k, v in entry.items() if k in SSHConnection.model_fields}
            )
        except Exception as e:
            console.print(
                f"[yellow]Skipping invalid entry '{entry.get('name', '?')}': "
                f"{describe_error(e)}[/yellow]"
            )
            skipped += 1
            continue

        if conn.name not in existing:
            manager.add_connection(conn)
            existing.add(conn.name)
            imported += 1
        elif overwrite:
            manager.update_connection(conn.name, conn)
            overwritten += 1
        else:
            console.print(f"[dim]Skipping '{conn.name}' (already exists)[/dim]")
            skipped += 1

    show_warnings(manager)
    parts = [
        f"[green]{imported} imported[/green]" if imported else "",
        f"[cyan]{overwritten} overwritten[/cyan]" if overwritten else "",
        f"[yellow]{skipped} skipped[/yellow]" if skipped else "",
    ]
    console.print("Import complete: " + ", ".join(p for p in parts if p))


@app.command()
@handle_errors
def backup(
    output_dir: Optional[Path] = typer.Option(None, help="Backup directory"),
) -> None:
    """Back up the SSH config and every folder file (manual backups are kept)."""
    manager = get_manager()
    files = [manager.config.config_file]
    files += [manager.folder_path(f) for f in manager.folders()]
    made = [manager.backup(path, dest_dir=output_dir, manual=True) for path in files]
    if not any(made):
        console.print("[yellow]No SSH config file found to back up[/yellow]")
    for path in made:
        if path:
            console.print(f"[green]Backup created: {path}[/green]")


@app.command()
@handle_errors
def config(
    action: str = typer.Argument(..., help="Action to perform: get, set, show"),
    key: Optional[str] = typer.Argument(None, help="Setting to get/set"),
    value: Optional[str] = typer.Argument(None, help="Value to set"),
) -> None:
    """Show or change sshm settings."""
    manager = ConfigManager()
    cfg = manager.load_config()
    keys = ", ".join(AppConfig.model_fields)

    if action == "show":
        console.print(f"[cyan]sshm settings[/cyan] [dim]({manager.config_path})[/dim]")
        for field, current in cfg.model_dump().items():
            console.print(f"  {field:<12} {current if current is not None else '-'}")
    elif action == "get":
        if not key:
            console.print_json(data=cfg.model_dump(mode="json"))
        elif key in AppConfig.model_fields:
            console.print(f"{key}: {getattr(cfg, key)}")
        else:
            raise ValueError(f"Unknown config key: {key}. Available keys: {keys}")
    elif action == "set":
        if not key or value is None:
            raise ValueError("Both key and value are required for 'set'")
        manager.set_setting(key, value)
        console.print(f"[green]Successfully updated {key}[/green]")
    else:
        raise ValueError("Invalid action. Use 'get', 'set', or 'show'")


@app.command(name="man")
@handle_errors
def manual(
    install: bool = typer.Option(
        False, "--install", help=f"Copy the page to {USER_MAN_DIR} for 'man sshm'"
    ),
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove that copy"),
) -> None:
    """Show the manual (the man page shipped with this version)."""
    installed = USER_MAN_DIR / "sshm.1"
    if uninstall:
        installed.unlink(missing_ok=True)
        console.print(f"[green]Removed {installed}[/green]")
        return

    with resources.as_file(resources.files("sshm") / "man" / "sshm.1") as page:
        if install:
            USER_MAN_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(page, installed)
            console.print(
                f"[green]Installed {installed}[/green] [dim]try: man sshm[/dim]"
            )
            return
        if shutil.which("man") is None:
            raise ValueError(f"'man' is not installed; the page is at {page}")
        if not installed.exists():
            console.print("[dim]Tip: 'sshm man --install' makes 'man sshm' work.[/dim]")
        subprocess.run(["man", str(page.resolve())], check=False)
