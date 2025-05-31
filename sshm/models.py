from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict
from pathlib import Path
import re


class SSHConnection(BaseModel):
    """Model representing an SSH connection entry."""

    name: str
    hostname: str
    user: str
    port: int = Field(default=22, ge=1, le=65535)
    identity_file: Optional[Path] = None
    extra_options: Dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        # SSH doesn't allow certain characters in host names
        invalid_chars = [" ", "\t", "\n", "*", "?"]
        if any(char in v for char in invalid_chars):
            raise ValueError(f'Name cannot contain: {", ".join(invalid_chars)}')
        return v.strip()

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v):
        if not v or not v.strip():
            raise ValueError("Hostname cannot be empty")
        v = v.strip()

        # Basic hostname validation
        if len(v) > 253:
            raise ValueError("Hostname too long (max 253 characters)")

        # Check for valid hostname pattern (basic validation)
        hostname_pattern = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
        if (
            not hostname_pattern.match(v)
            and not v.replace(".", "").replace(":", "").isdigit()
        ):
            # Allow IP addresses and complex hostnames
            pass

        return v

    @field_validator("user")
    @classmethod
    def validate_user(cls, v):
        if not v or not v.strip():
            raise ValueError("User cannot be empty")
        return v.strip()

    @field_validator("identity_file")
    @classmethod
    def validate_identity_file(cls, v):
        if v is not None:
            # Expand user home directory
            expanded_path = Path(str(v)).expanduser()
            return expanded_path
        return v

    def to_config_string(self) -> str:
        """Convert the connection to SSH config format."""
        lines = [f"Host {self.name}"]
        lines.append(f"    HostName {self.hostname}")
        lines.append(f"    User {self.user}")
        if self.port != 22:
            lines.append(f"    Port {self.port}")

        if self.identity_file:
            lines.append(f"    IdentityFile {self.identity_file}")

        for key, value in self.extra_options.items():
            lines.append(f"    {key} {value}")

        return "\n".join(lines)

    @classmethod
    def from_config_block(cls, config_block: str) -> "SSHConnection":
        """Create a connection from an SSH config block."""
        lines = config_block.strip().split("\n")
        if not lines or not lines[0].strip().startswith("Host "):
            raise ValueError("Invalid SSH config block: must start with 'Host'")

        name = lines[0].split("Host", 1)[1].strip()
        if not name:
            raise ValueError("Host name cannot be empty")

        data = {"name": name, "hostname": name, "user": "root", "extra_options": {}}

        for line in lines[1:]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split(None, 1)
            if len(parts) != 2:
                continue

            key, value = parts[0], parts[1]

            if key.lower() == "hostname":
                data["hostname"] = value
            elif key.lower() == "user":
                data["user"] = value
            elif key.lower() == "port":
                try:
                    data["port"] = int(value)
                except ValueError:
                    continue
            elif key.lower() == "identityfile":
                data["identity_file"] = Path(value).expanduser()
            else:
                data["extra_options"][key] = value

        # Validate required fields
        if not data.get("hostname") or not data.get("user"):
            raise ValueError("SSH config block missing required hostname or user")

        return cls(**data)


class AppConfig(BaseModel):
    """Model representing application configuration."""

    config_file: Path = Field(default=Path.home() / ".ssh" / "config")
    backup_dir: Path = Field(default=Path.home() / ".ssh" / "backups")
    default_key: Optional[Path] = None
    auto_backup: bool = True
