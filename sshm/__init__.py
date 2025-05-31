"""SSH Manager - A modern CLI tool to manage SSH connections."""

__version__ = "0.1.0"
__author__ = "palace22"

from .models import SSHConnection, AppConfig
from .manager import SSHManager

__all__ = ["SSHConnection", "AppConfig", "SSHManager"]
