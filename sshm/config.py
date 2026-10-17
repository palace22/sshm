"""Persistent sshm settings (``~/.ssh-manager/config.json``)."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .models import AppConfig

# Point sshm at another settings file, e.g. to try it on a sandbox config.
CONFIG_ENV = "SSHM_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".ssh-manager" / "config.json"

PATH_KEYS = ("config_file", "backup_dir", "folders_dir", "default_key")
_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


def parse_bool(value: Any) -> bool:
    """Parse a boolean from CLI text ('false' must not become True)."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"Expected a boolean (true/false), got '{value}'")


class ConfigManager:
    """Manages persistent configuration for SSH Manager."""

    def __init__(self, config_path: Optional[Path] = None):
        env = os.environ.get(CONFIG_ENV)
        self.config_path = config_path or (
            Path(env).expanduser() if env else DEFAULT_CONFIG_PATH
        )

    @property
    def data_dir(self) -> Path:
        """Directory for sshm's own state (settings, connection history)."""
        return self.config_path.parent

    def load_config(self) -> AppConfig:
        """Load configuration from file or return defaults."""
        if not self.config_path.exists():
            return AppConfig()

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            for key in PATH_KEYS:
                if data.get(key):
                    data[key] = Path(data[key]).expanduser()
            return AppConfig(**data)
        except (OSError, TypeError, ValueError) as e:
            print(
                f"Warning: Failed to load config from {self.config_path}: {e}",
                file=sys.stderr,
            )
            return AppConfig()

    def save_config(self, config: AppConfig) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.config_path.write_text(
                json.dumps(config.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise ValueError(f"Failed to save config to {self.config_path}: {e}")

    def set_setting(self, key: str, value: Any) -> None:
        """Set a specific configuration setting."""
        config = self.load_config()
        if key not in AppConfig.model_fields:
            raise ValueError(f"Unknown configuration key: {key}")

        if key in PATH_KEYS:
            value = Path(value).expanduser() if value else None
        elif key == "auto_backup":
            value = parse_bool(value)
        elif key == "max_backups":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"max_backups must be an integer, got '{value}'")
            if value < 0:
                raise ValueError("max_backups cannot be negative (0 = unlimited)")

        self.save_config(AppConfig(**{**config.model_dump(), key: value}))
