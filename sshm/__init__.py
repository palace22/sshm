"""sshm - manage and connect to the hosts in your ~/.ssh/config."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sshm")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+local"

from .manager import SSHManager  # noqa: E402
from .models import AppConfig, SSHConnection  # noqa: E402

__all__ = ["SSHConnection", "AppConfig", "SSHManager", "__version__"]
