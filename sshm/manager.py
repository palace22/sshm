import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from .models import SSHConnection, AppConfig

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
        if not self.config.auto_backup:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.config.backup_dir / f"config.{timestamp}.bak"
        shutil.copy2(self.config.config_file, backup_file)

    def _read_config(self) -> str:
        """Read the SSH config file."""
        if not self.config.config_file.exists():
            return ""
        return self.config.config_file.read_text()

    def _write_config(self, content: str) -> None:
        """Write content to the SSH config file."""
        if self.config.config_file.exists():
            self._backup_config()
        self.config.config_file.write_text(content)

    def list_connections(self, search: Optional[str] = None) -> List[SSHConnection]:
        """List all SSH connections, optionally filtered by search term."""
        config_content = self._read_config()
        if not config_content:
            return []

        connections = []
        current_block = []
        
        for line in config_content.split("\n"):
            if line.strip().startswith("Host ") and current_block:
                conn = SSHConnection.from_config_block("\n".join(current_block))
                if not search or search.lower() in conn.name.lower():
                    connections.append(conn)
                current_block = []
            if line.strip():
                current_block.append(line)

        if current_block:
            conn = SSHConnection.from_config_block("\n".join(current_block))
            if not search or search.lower() in conn.name.lower():
                connections.append(conn)

        return connections

    def add_connection(self, connection: SSHConnection) -> None:
        """Add a new SSH connection."""
        existing = self.list_connections()
        if any(conn.name == connection.name for conn in existing):
            raise ValueError(f"Connection '{connection.name}' already exists")

        config_content = self._read_config()
        new_content = config_content.rstrip() + "\n\n" + connection.to_config_string()
        self._write_config(new_content)

    def update_connection(self, name: str, connection: SSHConnection) -> None:
        """Update an existing SSH connection."""
        if name != connection.name:
            raise ValueError("Connection name cannot be changed")

        connections = self.list_connections()
        if not any(conn.name == name for conn in connections):
            raise ValueError(f"Connection '{name}' not found")

        # Rebuild config file with updated connection
        new_connections = [
            conn if conn.name != name else connection
            for conn in connections
        ]
        
        content = "\n\n".join(conn.to_config_string() for conn in new_connections)
        self._write_config(content)

    def remove_connection(self, name: str) -> None:
        """Remove an SSH connection."""
        connections = self.list_connections()
        new_connections = [conn for conn in connections if conn.name != name]
        
        if len(connections) == len(new_connections):
            raise ValueError(f"Connection '{name}' not found")
            
        content = "\n\n".join(conn.to_config_string() for conn in new_connections)
        self._write_config(content)

    def get_connection(self, name: str) -> SSHConnection:
        """Get a specific SSH connection by name."""
        connections = self.list_connections()
        for conn in connections:
            if conn.name == name:
                return conn
        raise ValueError(f"Connection '{name}' not found")