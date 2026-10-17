"""Command line interface. Importing the command modules registers them."""

from . import connect, data, hosts, organize  # noqa: F401
from .common import app


def main() -> None:
    """Entry point for the CLI."""
    app()
