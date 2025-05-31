"""Tests for SSH Manager core functionality."""

import pytest
import tempfile
from pathlib import Path
from sshm.models import SSHConnection, AppConfig
from sshm.manager import SSHManager


class TestSSHManager:
    """Test SSH manager functionality."""

    @pytest.fixture
    def temp_config(self):
        """Create temporary config for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".config", delete=False) as f:
            config_file = Path(f.name)

        backup_dir = Path(tempfile.mkdtemp())
        config = AppConfig(
            config_file=config_file, backup_dir=backup_dir, auto_backup=True
        )

        yield config

        # Cleanup
        if config_file.exists():
            config_file.unlink()
        if backup_dir.exists():
            import shutil

            shutil.rmtree(backup_dir)

    @pytest.fixture
    def manager(self, temp_config):
        """Create SSH manager with temporary config."""
        return SSHManager(temp_config)

    @pytest.fixture
    def sample_connection(self):
        """Create a sample SSH connection."""
        return SSHConnection(
            name="test-server", hostname="example.com", user="testuser", port=2222
        )

    def test_add_connection(self, manager, sample_connection):
        """Test adding a new SSH connection."""
        manager.add_connection(sample_connection)
        connections = manager.list_connections()

        assert len(connections) == 1
        assert connections[0].name == "test-server"
        assert connections[0].hostname == "example.com"

    def test_add_duplicate_connection(self, manager, sample_connection):
        """Test adding duplicate connection raises error."""
        manager.add_connection(sample_connection)

        with pytest.raises(ValueError, match="already exists"):
            manager.add_connection(sample_connection)

    def test_get_connection(self, manager, sample_connection):
        """Test retrieving a specific connection."""
        manager.add_connection(sample_connection)

        retrieved = manager.get_connection("test-server")
        assert retrieved.name == sample_connection.name
        assert retrieved.hostname == sample_connection.hostname

    def test_get_nonexistent_connection(self, manager):
        """Test retrieving non-existent connection raises error."""
        with pytest.raises(ValueError, match="not found"):
            manager.get_connection("nonexistent")

    def test_update_connection(self, manager, sample_connection):
        """Test updating an existing connection."""
        manager.add_connection(sample_connection)

        updated_connection = SSHConnection(
            name="test-server", hostname="new-example.com", user="newuser", port=22
        )

        manager.update_connection("test-server", updated_connection)

        retrieved = manager.get_connection("test-server")
        assert retrieved.hostname == "new-example.com"
        assert retrieved.user == "newuser"
        assert retrieved.port == 22

    def test_remove_connection(self, manager, sample_connection):
        """Test removing a connection."""
        manager.add_connection(sample_connection)
        assert len(manager.list_connections()) == 1

        manager.remove_connection("test-server")
        assert len(manager.list_connections()) == 0

    def test_remove_nonexistent_connection(self, manager):
        """Test removing non-existent connection raises error."""
        with pytest.raises(ValueError, match="not found"):
            manager.remove_connection("nonexistent")

    def test_list_connections_with_search(self, manager):
        """Test listing connections with search filter."""
        conn1 = SSHConnection(name="web-server", hostname="web.example.com", user="www")
        conn2 = SSHConnection(
            name="db-server", hostname="db.example.com", user="postgres"
        )
        conn3 = SSHConnection(
            name="test-web", hostname="test.example.com", user="tester"
        )

        manager.add_connection(conn1)
        manager.add_connection(conn2)
        manager.add_connection(conn3)

        # Search by name
        results = manager.list_connections("web")
        assert len(results) == 2
        assert all("web" in conn.name.lower() for conn in results)

        # Search by hostname
        results = manager.list_connections("db.example")
        assert len(results) == 1
        assert results[0].name == "db-server"

        # Search by user
        results = manager.list_connections("postgres")
        assert len(results) == 1
        assert results[0].name == "db-server"

    def test_parse_existing_config(self, temp_config):
        """Test parsing existing SSH config file."""
        config_content = """Host web-server
    HostName web.example.com
    User www
    Port 80
    IdentityFile ~/.ssh/web_key

Host db-server
    HostName db.example.com
    User postgres
    Port 5432
"""
        temp_config.config_file.write_text(config_content)

        manager = SSHManager(temp_config)
        connections = manager.list_connections()

        assert len(connections) == 2

        web_conn = next(conn for conn in connections if conn.name == "web-server")
        assert web_conn.hostname == "web.example.com"
        assert web_conn.user == "www"
        assert web_conn.port == 80

        db_conn = next(conn for conn in connections if conn.name == "db-server")
        assert db_conn.hostname == "db.example.com"
        assert db_conn.user == "postgres"
        assert db_conn.port == 5432
