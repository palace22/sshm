"""Tests for SSH Manager models."""

from pathlib import Path

import pytest

from sshm.models import AppConfig, SSHConnection


class TestSSHConnection:
    """Test SSH connection model."""

    def test_valid_connection(self):
        """Test creating a valid SSH connection."""
        conn = SSHConnection(
            name="test-server",
            hostname="example.com",
            user="testuser",
            port=2222,
            identity_file=Path("~/.ssh/id_rsa"),
        )
        assert conn.name == "test-server"
        assert conn.hostname == "example.com"
        assert conn.user == "testuser"
        assert conn.port == 2222
        assert conn.identity_file == Path("~/.ssh/id_rsa").expanduser()

    def test_default_values(self):
        """Test default values for SSH connection."""
        conn = SSHConnection(name="test", hostname="example.com", user="user")
        assert conn.port == 22
        assert conn.identity_file is None
        assert conn.extra_options == {}

    def test_invalid_name(self):
        """Test validation of connection name."""
        with pytest.raises(ValueError, match="Name cannot be empty"):
            SSHConnection(name="", hostname="example.com", user="user")

        with pytest.raises(ValueError, match="Name cannot contain"):
            SSHConnection(name="test host", hostname="example.com", user="user")

    def test_invalid_hostname(self):
        """Test validation of hostname."""
        with pytest.raises(ValueError, match="Hostname cannot be empty"):
            SSHConnection(name="test", hostname="", user="user")

    def test_invalid_user(self):
        """Test validation of user."""
        with pytest.raises(ValueError, match="User cannot be empty"):
            SSHConnection(name="test", hostname="example.com", user="")

    def test_invalid_port(self):
        """Test validation of port."""
        with pytest.raises(ValueError):
            SSHConnection(name="test", hostname="example.com", user="user", port=0)

        with pytest.raises(ValueError):
            SSHConnection(name="test", hostname="example.com", user="user", port=70000)

    def test_to_config_string(self):
        """Test SSH config string generation."""
        conn = SSHConnection(
            name="test-server",
            hostname="example.com",
            user="testuser",
            port=2222,
            identity_file=Path("~/.ssh/id_rsa"),
            extra_options={"StrictHostKeyChecking": "no"},
        )
        config_str = conn.to_config_string()

        assert "Host test-server" in config_str
        assert "HostName example.com" in config_str
        assert "User testuser" in config_str
        assert "Port 2222" in config_str
        assert "IdentityFile" in config_str
        assert "StrictHostKeyChecking no" in config_str

    def test_from_config_block(self):
        """Test parsing SSH config block."""
        config_block = """Host test-server
    HostName example.com
    User testuser
    Port 2222
    IdentityFile ~/.ssh/id_rsa
    StrictHostKeyChecking no"""

        conn = SSHConnection.from_config_block(config_block)
        assert conn.name == "test-server"
        assert conn.hostname == "example.com"
        assert conn.user == "testuser"
        assert conn.port == 2222
        assert "StrictHostKeyChecking" in conn.extra_options


class TestAppConfig:
    """Test application configuration model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AppConfig()
        assert config.config_file == Path.home() / ".ssh" / "config"
        assert config.backup_dir == Path.home() / ".ssh" / "backups"
        assert config.auto_backup is True
        assert config.default_key is None
