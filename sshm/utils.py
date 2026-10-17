"""Small checks used by the CLI."""

import socket
from pathlib import Path
from typing import Optional, Tuple

_KEY_HEADERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
)


def validate_ssh_key(key_path: Path) -> Tuple[bool, Optional[str]]:
    """Check that a private key exists, is private (600/400) and looks like a key.

    Returns ``(is_valid, error_message)``.
    """
    if not key_path.exists():
        return False, f"Key file does not exist: {key_path}"
    if not key_path.is_file():
        return False, f"Key path is not a file: {key_path}"

    try:
        permissions = oct(key_path.stat().st_mode)[-3:]
        content = key_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return False, f"Cannot read key file: {e}"

    if permissions not in ("600", "400"):
        return False, f"Insecure key permissions: {permissions} (should be 600 or 400)"
    if not any(header in content for header in _KEY_HEADERS):
        return False, "File does not appear to be a valid SSH private key"
    return True, None


def check_tcp_port(
    hostname: str, port: int = 22, timeout: float = 5
) -> Tuple[bool, Optional[str]]:
    """Check that ``hostname:port`` accepts TCP connections.

    Returns ``(is_reachable, error_message)``.
    """
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return True, None
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except socket.timeout:
        return False, f"Connection timeout to {hostname}:{port}"
    except OSError as e:
        return False, f"Cannot reach {hostname}:{port}: {e.strerror or e}"
