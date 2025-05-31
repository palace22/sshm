"""Utility functions for SSH Manager."""

import re
import socket
from pathlib import Path
from typing import Optional, Tuple
import subprocess


def validate_ssh_key(key_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Validate an SSH private key file.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not key_path.exists():
        return False, f"Key file does not exist: {key_path}"

    if not key_path.is_file():
        return False, f"Key path is not a file: {key_path}"

    # Check file permissions (should be 600 or 400)
    try:
        permissions = oct(key_path.stat().st_mode)[-3:]
        if permissions not in ["600", "400"]:
            return (
                False,
                f"Insecure key permissions: {permissions} (should be 600 or 400)",
            )
    except OSError as e:
        return False, f"Cannot check permissions: {e}"

    # Try to read and validate key format
    try:
        content = key_path.read_text(encoding="utf-8")

        # Check for common SSH key headers
        key_headers = [
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----BEGIN DSA PRIVATE KEY-----",
            "-----BEGIN EC PRIVATE KEY-----",
            "-----BEGIN PRIVATE KEY-----",
        ]

        if not any(header in content for header in key_headers):
            return False, "File does not appear to be a valid SSH private key"

    except (OSError, UnicodeDecodeError) as e:
        return False, f"Cannot read key file: {e}"

    return True, None


def test_ssh_connectivity(
    hostname: str, port: int = 22, timeout: int = 5
) -> Tuple[bool, Optional[str]]:
    """
    Test if SSH port is accessible on a host.

    Returns:
        Tuple of (is_reachable, error_message)
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((hostname, port))
        sock.close()

        if result == 0:
            return True, None
        else:
            return False, f"Connection refused on {hostname}:{port}"

    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except socket.timeout:
        return False, f"Connection timeout to {hostname}:{port}"
    except Exception as e:
        return False, f"Connection error: {e}"


def validate_hostname(hostname: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a hostname or IP address.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not hostname or not hostname.strip():
        return False, "Hostname cannot be empty"

    hostname = hostname.strip()

    # Check length
    if len(hostname) > 253:
        return False, "Hostname too long (max 253 characters)"

    # Check for IP address (basic validation)
    ip_pattern = re.compile(
        r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    )
    if ip_pattern.match(hostname):
        return True, None

    # Check for IPv6 (basic validation)
    if ":" in hostname and hostname.count(":") >= 2:
        try:
            socket.inet_pton(socket.AF_INET6, hostname)
            return True, None
        except socket.error:
            pass

    # Validate hostname format
    if hostname.startswith("-") or hostname.endswith("-"):
        return False, "Hostname cannot start or end with hyphen"

    # Check each label in the hostname
    labels = hostname.split(".")
    for label in labels:
        if not label:
            return False, "Hostname cannot have empty labels"
        if len(label) > 63:
            return False, "Hostname label too long (max 63 characters)"
        if not re.match(r"^[a-zA-Z0-9-]+$", label):
            return False, f"Invalid characters in hostname label: {label}"
        if label.startswith("-") or label.endswith("-"):
            return False, f"Hostname label cannot start or end with hyphen: {label}"

    return True, None


def get_ssh_version() -> Optional[str]:
    """Get the installed SSH client version."""
    try:
        result = subprocess.run(
            ["ssh", "-V"], capture_output=True, text=True, timeout=5
        )
        # SSH version is typically in stderr
        version_line = result.stderr.strip()
        if version_line:
            return version_line
        return result.stdout.strip()
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None


def format_connection_string(hostname: str, user: str, port: int = 22) -> str:
    """Format a connection string for display."""
    if port == 22:
        return f"{user}@{hostname}"
    else:
        return f"{user}@{hostname}:{port}"


def sanitize_connection_name(name: str) -> str:
    """Sanitize a connection name to be safe for SSH config."""
    # Remove invalid characters and replace with underscores
    sanitized = re.sub(r"[^\w\-.]", "_", name.strip())

    # Remove leading/trailing underscores and dots
    sanitized = sanitized.strip("_.")

    # Ensure it's not empty
    if not sanitized:
        sanitized = "connection"

    return sanitized


def backup_file(file_path: Path, backup_dir: Path) -> Optional[Path]:
    """
    Create a backup of a file with timestamp.

    Returns:
        Path to backup file if successful, None otherwise
    """
    if not file_path.exists():
        return None

    try:
        from datetime import datetime
        import shutil

        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.name}.{timestamp}.bak"
        backup_path = backup_dir / backup_name

        shutil.copy2(file_path, backup_path)
        return backup_path

    except (OSError, IOError):
        return None


def is_ssh_config_valid(config_content: str) -> Tuple[bool, Optional[str]]:
    """
    Validate SSH config content for basic syntax errors.

    Returns:
        Tuple of (is_valid, error_message)
    """
    lines = config_content.split("\n")
    current_host = None

    for line_num, line in enumerate(lines, 1):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Check for proper indentation in host blocks
        if line.startswith(" ") or line.startswith("\t"):
            if current_host is None:
                return (
                    False,
                    f"Line {line_num}: Configuration option outside of Host block",
                )

        # Check Host declarations
        if line.lower().startswith("host "):
            host_part = line[5:].strip()
            if not host_part:
                return False, f"Line {line_num}: Empty Host declaration"
            current_host = host_part

        # Check for basic option format
        if not line.lower().startswith("host ") and not line.startswith((" ", "\t")):
            # This might be a global option, which is valid
            pass

    return True, None
