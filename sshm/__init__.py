"""SSH Manager - A modern CLI tool to manage SSH connections."""

__version__ = "0.1.0"
__author__ = "palace22"

from .manager import SSHManager
from .models import AppConfig, SSHConnection

__all__ = ["SSHConnection", "AppConfig", "SSHManager"]
