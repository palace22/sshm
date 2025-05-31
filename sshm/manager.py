import re
import shutil
from datetime import datetime
from typing import List, Optional, Tuple

from rapidfuzz import process

from .models import AppConfig, SSHConnection


class SSHManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Ensure necessary directories exist."""
        self.config.config_file.parent.mkdir(parents=True, exist_ok=True)
        if self.config.auto_backup:
            self.config.backup_dir.mkdir(parents=True, exist_ok=True)

    def _backup_config(self) -> None:
        """Create a backup of the SSH config file."""
        if not self.config.auto_backup or not self.config.config_file.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.config.backup_dir / f"config.{timestamp}.bak"
        try:
            shutil.copy2(self.config.config_file, backup_file)
        except (IOError, OSError) as e:
            print(f"Warning: Failed to create backup: {e}")

    def _read_config(self) -> str:
        """Read the SSH config file."""
        if not self.config.config_file.exists():
            return ""
        try:
            return self.config.config_file.read_text(encoding="utf-8")
        except (IOError, UnicodeDecodeError) as e:
            raise ValueError(f"Failed to read SSH config file: {e}")

    def _write_config(self, content: str) -> None:
        """Write content to the SSH config file."""
        self._backup_config()
        try:
            self.config.config_file.write_text(content, encoding="utf-8")
        except (IOError, OSError) as e:
            raise ValueError(f"Failed to write SSH config file: {e}")

    def _parse_ssh_config(self, content: str) -> List[SSHConnection]:
        """Parse SSH config content into SSHConnection objects."""
        connections = []

        # Split by Host entries using regex for better parsing
        host_pattern = re.compile(r"^Host\s+(.+)$", re.MULTILINE | re.IGNORECASE)
        blocks = host_pattern.split(content)

        # Process each host block (skip first empty block if any)
        for i in range(1, len(blocks), 2):
            if i + 1 < len(blocks):
                host_name = blocks[i].strip()
                host_config = blocks[i + 1].strip()

                # Skip wildcard hosts and includes
                if (
                    "*" in host_name
                    or "?" in host_name
                    or host_name.lower() in ["*", "include"]
                ):
                    continue

                try:
                    config_block = f"Host {host_name}\n{host_config}"
                    connection = SSHConnection.from_config_block(config_block)
                    connections.append(connection)
                except Exception as e:
                    # Log error but continue parsing
                    print(f"Warning: Failed to parse host '{host_name}': {e}")

        return connections

    def list_connections(self, search: Optional[str] = None) -> List[SSHConnection]:
        """List all SSH connections, optionally filtered by search term."""
        config_content = self._read_config()
        if not config_content:
            return []

        connections = self._parse_ssh_config(config_content)

        if search:
            search_lower = search.lower()
            connections = [
                conn
                for conn in connections
                if search_lower in conn.name.lower()
                or search_lower in conn.hostname.lower()
                or search_lower in conn.user.lower()
            ]

        return connections

    def add_connection(self, connection: SSHConnection) -> None:
        """Add a new SSH connection."""
        existing = self.list_connections()
        if any(conn.name == connection.name for conn in existing):
            raise ValueError(f"Connection '{connection.name}' already exists")

        config_content = self._read_config()
        if config_content and not config_content.endswith("\n"):
            config_content += "\n"

        new_content = config_content + "\n" + connection.to_config_string() + "\n"
        self._write_config(new_content)

    def update_connection(self, name: str, connection: SSHConnection) -> None:
        """Update an existing SSH connection."""
        if name != connection.name:
            raise ValueError("Connection name cannot be changed")

        connections = self.list_connections()
        if not any(conn.name == name for conn in connections):
            raise ValueError(f"Connection '{name}' not found")

        # Rebuild config file with updated connection
        updated_connections = [
            connection if conn.name == name else conn for conn in connections
        ]

        # Format with proper spacing
        content_parts = []
        for conn in updated_connections:
            content_parts.append(conn.to_config_string())

        content = "\n\n".join(content_parts)
        if content:
            content += "\n"
        self._write_config(content)

    def remove_connection(self, name: str) -> None:
        """Remove an SSH connection."""
        connections = self.list_connections()
        filtered_connections = [conn for conn in connections if conn.name != name]

        if len(connections) == len(filtered_connections):
            raise ValueError(f"Connection '{name}' not found")

        # Format with proper spacing
        content_parts = []
        for conn in filtered_connections:
            content_parts.append(conn.to_config_string())

        content = "\n\n".join(content_parts)
        if content:
            content += "\n"
        self._write_config(content)

    def get_connection(self, name: str) -> SSHConnection:
        """Get a specific SSH connection by name."""
        connections = self.list_connections()
        for conn in connections:
            if conn.name == name:
                return conn
        raise ValueError(f"Connection '{name}' not found")

    def find_best_matches(
        self, search_term: str, limit: int = 5
    ) -> List[Tuple[SSHConnection, int]]:
        """Find the best matching connections using fuzzy search."""
        connections = self.list_connections()
        if not connections:
            return []

        # Get connection names for fuzzy matching
        connection_names = [conn.name for conn in connections]

        # Find fuzzy matches
        matches = process.extract(search_term, connection_names, limit=limit)

        # Return connections with their scores
        result = []
        for match_name, score, index in matches:
            for conn in connections:
                if conn.name == match_name:
                    result.append((conn, score))
                    break

        return result

    def find_connection_fuzzy(
        self, search_term: str, min_score: int = 60
    ) -> Optional[SSHConnection]:
        """Find a connection using fuzzy search, return None if no good match."""
        matches = self.find_best_matches(search_term, limit=1)
        if matches and matches[0][1] >= min_score:
            return matches[0][0]
        return None

    def suggest_connections(
        self, partial_name: str, limit: int = 5
    ) -> List[SSHConnection]:
        """Suggest connections based on partial name input."""
        if not partial_name:
            return self.list_connections()[:limit]

        matches = self.find_best_matches(partial_name, limit=limit)
        return [
            match[0] for match in matches if match[1] >= 40
        ]  # Lower threshold for suggestions
