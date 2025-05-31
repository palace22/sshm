"""Configuration management for SSH Manager."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .models import AppConfig


class ConfigManager:
    """Manages persistent configuration for SSH Manager."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".ssh-manager" / "config.json"
        self._config_cache: Optional[Dict[str, Any]] = None

    def load_config(self) -> AppConfig:
        """Load configuration from file or return defaults."""
        if not self.config_path.exists():
            return AppConfig()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Convert string paths back to Path objects
            if "config_file" in data:
                data["config_file"] = Path(data["config_file"]).expanduser()
            if "backup_dir" in data:
                data["backup_dir"] = Path(data["backup_dir"]).expanduser()
            if "default_key" in data and data["default_key"]:
                data["default_key"] = Path(data["default_key"]).expanduser()

            return AppConfig(**data)
        except (json.JSONDecodeError, IOError, KeyError, TypeError) as e:
            print(f"Warning: Failed to load config from {self.config_path}: {e}")
            return AppConfig()

    def save_config(self, config: AppConfig) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert Path objects to strings for JSON serialization
        data = config.model_dump()
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (IOError, OSError) as e:
            raise ValueError(f"Failed to save config to {self.config_path}: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific configuration setting."""
        config = self.load_config()
        return getattr(config, key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Set a specific configuration setting."""
        config = self.load_config()
        if not hasattr(config, key):
            raise ValueError(f"Unknown configuration key: {key}")

        # Type conversion for Path fields
        if key in ["config_file", "backup_dir", "default_key"] and value:
            value = Path(value).expanduser()
        elif key == "auto_backup":
            value = bool(value)

        setattr(config, key, value)
        self.save_config(config)
