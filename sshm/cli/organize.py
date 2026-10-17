"""Organizing hosts: tags (virtual labels) and folders (real files)."""

from typing import List

import typer
from rich import box
from rich.table import Table

from ..ui import console
from ..ui.tables import connection_tree, tag_text
from .common import (
    HOST_ARG,
    app,
    complete_folder,
    complete_tag,
    get_manager,
    handle_errors,
    show_warnings,
    split_list,
)

tag_app = typer.Typer(
    help="Tag hosts. Tags are stored as a '# sshm: tags=...' comment that ssh "
    "ignores; a host can have many.",
    no_args_is_help=True,
)
folder_app = typer.Typer(
    help="Group hosts in folders. Each folder is a real file under "
    "~/.ssh/sshm.d/ (e.g. work/acme -> sshm.d/work/acme.conf) that ssh loads "
    "through one Include line.",
    no_args_is_help=True,
)
app.add_typer(tag_app, name="tag")
app.add_typer(folder_app, name="folder")

TAGS_ARG = typer.Argument(..., help="Tags", autocompletion=complete_tag)


def _parse_tags(values: List[str]) -> List[str]:
    return [t.lstrip("@") for value in values for t in split_list(value)]


@tag_app.command("add")
@handle_errors
def tag_add(name: str = HOST_ARG, tags: List[str] = TAGS_ARG) -> None:
    """Add tags to a host."""
    manager = get_manager()
    conn = manager.get_connection(name)
    updated = manager.set_tags(name, conn.tags + _parse_tags(tags))
    console.print(f"[green]{updated.name}[/green] {tag_text(updated.tags)}")


@tag_app.command("rm")
@handle_errors
def tag_rm(name: str = HOST_ARG, tags: List[str] = TAGS_ARG) -> None:
    """Remove tags from a host."""
    manager = get_manager()
    conn = manager.get_connection(name)
    drop = set(_parse_tags(tags))
    updated = manager.set_tags(name, [t for t in conn.tags if t not in drop])
    console.print(f"[green]{updated.name}[/green] {tag_text(updated.tags) or '-'}")


@tag_app.command("list")
@handle_errors
def tag_list() -> None:
    """List every tag with the number of hosts using it."""
    manager = get_manager()
    counts = manager.tag_counts()
    show_warnings(manager)
    if not counts:
        console.print("[yellow]No tags yet. Try: sshm tag add HOST prod[/yellow]")
        return
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    table.add_column("TAG", style="magenta")
    table.add_column("HOSTS", justify="right")
    for tag, count in counts.items():
        table.add_row(f"@{tag}", str(count))
    console.print(table)


@folder_app.command("list")
@handle_errors
def folder_list() -> None:
    """Show folders and their hosts as a tree."""
    manager = get_manager()
    connections = manager.list_connections()
    show_warnings(manager)
    console.print(
        connection_tree(connections, manager.folders(), str(manager.config.config_file))
    )


@folder_app.command("add")
@handle_errors
def folder_add(
    folder: str = typer.Argument(..., help="Folder name, e.g. work or work/acme"),
) -> None:
    """Create a folder (and the Include line in ~/.ssh/config, once)."""
    path = get_manager().create_folder(folder)
    console.print(f"[green]Folder '{folder}' ready:[/green] [dim]{path}[/dim]")


@folder_app.command("rm")
@handle_errors
def folder_rm(
    folder: str = typer.Argument(..., help="Folder", autocompletion=complete_folder),
) -> None:
    """Delete an empty folder."""
    get_manager().remove_folder(folder)
    console.print(f"[green]Removed folder '{folder}'[/green]")


@app.command()
@handle_errors
def mv(
    name: str = HOST_ARG,
    folder: str = typer.Argument(
        ...,
        help="Destination folder ('/' = main ~/.ssh/config)",
        autocompletion=complete_folder,
    ),
) -> None:
    """Move a host into a folder (its block moves unchanged)."""
    manager = get_manager()
    destination = None if folder.strip() in ("/", "") else folder
    manager.move_connection(name, destination)
    show_warnings(manager)
    where = f"folder '{destination}'" if destination else "the main config"
    console.print(f"[green]Moved '{name}' to {where}[/green]")
