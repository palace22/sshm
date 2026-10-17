import json

import pytest

from sshm.manager import SSHManager
from sshm.models import AppConfig


@pytest.fixture
def make_manager(tmp_path):
    """Build a manager over a sandbox config; never touches the real ~/.ssh."""

    def make(text: str = "", **settings) -> SSHManager:
        config_file = tmp_path / "ssh" / "config"
        config_file.parent.mkdir(exist_ok=True)
        config_file.write_text(text)
        config = AppConfig(
            config_file=config_file,
            backup_dir=tmp_path / "backups",
            folders_dir=tmp_path / "ssh" / "sshm.d",
            **settings,
        )
        return SSHManager(config)

    return make


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the CLI at a sandbox through SSHM_CONFIG. Returns the ssh config path."""
    config_file = tmp_path / "ssh" / "config"
    config_file.parent.mkdir()
    settings = tmp_path / "sshm" / "config.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "config_file": str(config_file),
                "backup_dir": str(tmp_path / "backups"),
                "folders_dir": str(tmp_path / "ssh" / "sshm.d"),
            }
        )
    )
    monkeypatch.setenv("SSHM_CONFIG", str(settings))
    monkeypatch.setenv("SSHM_NO_ANIM", "1")
    return config_file
