"""The Typer app and helpers shared by every command module."""

import functools
import os
import shutil
import subprocess
import sys
from typing import Any, Callable, List, Optional, Tuple, TypeVar

import typer
from pydantic import ValidationError
from rich.prompt import Prompt

from ..config import ConfigManager
from ..history import History
from ..manager import SSHManager
from ..models import SSHConnection
from ..tabs import TabSession
from ..ui import console, err_console, picker
from ..ui.tables import target_text

app = typer.Typer(
    help="sshm - manage and connect to the hosts in your ~/.ssh/config.\n\n"
    "Run without a command to open the interactive host picker.",
    epilog="Manual: sshm man  |  Docs: https://github.com/palace22/sshm",
    no_args_is_help=False,
    rich_markup_mode="rich",
)

F = TypeVar("F", bound=Callable[..., Any])


def get_manager() -> SSHManager:
    """Get an instance of SSHManager with loaded config."""
    return SSHManager(ConfigManager().load_config())


def get_history() -> History:
    return History(ConfigManager().data_dir / "history.json")


def get_tabs() -> TabSession:
    return TabSession(ConfigManager().data_dir / "tmux.conf")


def describe_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        err = e.errors()[0]
        field = ".".join(str(part) for part in err["loc"])
        return f"{field}: {err['msg']}" if field else err["msg"]
    return str(e)


def handle_errors(func: F) -> F:
    """Turn unexpected exceptions into a red one-line error and exit code 1."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except KeyboardInterrupt:
            err_console.print("\n[yellow]Cancelled.[/yellow]")
            raise typer.Exit(130)
        except Exception as e:
            err_console.print(f"[red]Error:[/red] {describe_error(e)}")
            raise typer.Exit(1)

    return wrapper  # type: ignore[return-value]


def show_warnings(manager: SSHManager) -> None:
    """Print non-fatal manager warnings to stderr."""
    for warning in manager.warnings:
        err_console.print(f"[yellow]Warning:[/yellow] [dim]{warning}[/dim]")


def complete_host(incomplete: str) -> List[Tuple[str, str]]:
    """Shell completion for host names: prefix matches first, then fuzzy."""
    try:
        manager = get_manager()
        connections = manager.list_connections()
        prefix = [
            (c.name, c.target)
            for c in connections
            if c.name.lower().startswith(incomplete.lower())
        ]
        if prefix or not incomplete:
            return prefix
        matches = manager.find_best_matches(incomplete, limit=10)
        return [(c.name, c.target) for c, score in matches if score >= 35]
    except Exception:
        return []


def complete_folder(incomplete: str) -> List[str]:
    try:
        return [f for f in get_manager().folders() if f.startswith(incomplete)]
    except Exception:
        return []


def complete_tag(incomplete: str) -> List[str]:
    try:
        tags = get_manager().tag_counts()
        return [t for t in tags if t.startswith(incomplete.lstrip("@"))]
    except Exception:
        return []


HOST_ARG = typer.Argument(..., help="Host name or alias", autocompletion=complete_host)


def clearable(value: Optional[str], current: Optional[str]) -> Optional[str]:
    """Resolve an update value: None keeps current, '' or '-' clears it."""
    if value is None:
        return current
    if value.strip() in ("", "-"):
        return None
    return value


def split_list(value: str) -> List[str]:
    return [item.strip() for item in value.replace(" ", ",").split(",") if item.strip()]


def choose(
    connections: List[SSHConnection],
    manager: SSHManager,
    query: str = "",
    title: str = "",
) -> List[SSHConnection]:
    """Let the user pick hosts: the picker on a terminal, a numbered list otherwise.

    Returns an empty list when cancelled.
    """
    if picker.supported():
        return picker.pick(connections, manager.score, console, query, title)

    shown = connections[:20]
    for i, conn in enumerate(shown, 1):
        console.print(
            f"[bold]{i:2}.[/bold] [cyan]{conn.name}[/cyan] "
            f"[dim]{target_text(conn)}[/dim]"
        )
    console.print(" [bold]0.[/bold] [red]Cancel[/red]")
    choice = Prompt.ask(
        "\nSelect connection",
        choices=[str(i) for i in range(len(shown) + 1)],
        default="1",
    )
    return [shown[int(choice) - 1]] if choice != "0" else []


def run_ssh(cmd: List[str]) -> None:
    """Hand the terminal over to ssh, exiting with its status."""
    if shutil.which(cmd[0]) is None:
        raise ValueError("ssh not found. Please install the OpenSSH client.")
    sys.stdout.flush()
    if os.name != "nt":
        # Replace this process: ssh gets the terminal and signals directly.
        os.execvp(cmd[0], cmd)
    raise typer.Exit(subprocess.run(cmd, check=False).returncode)
