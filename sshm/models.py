import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .sshconfig import Block, SSHConfigDocument, quote, unquote

_INVALID_NAME_CHARS = [" ", "\t", "\n", "*", "?"]
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9_.:%\[\]-]+$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_FOLDER_PART_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
MAX_FOLDER_DEPTH = 3


def validate_alias(v: str) -> str:
    """Validate a Host alias (the name used with ``ssh <alias>``)."""
    if not v or not v.strip():
        raise ValueError("Name cannot be empty")
    # SSH doesn't allow certain characters in host names
    if any(char in v for char in _INVALID_NAME_CHARS):
        raise ValueError(f'Name cannot contain: {", ".join(_INVALID_NAME_CHARS)}')
    v = v.strip()
    if v.startswith("!"):
        raise ValueError("Name cannot start with '!' (negated pattern)")
    return v


def validate_tag(v: str) -> str:
    v = v.strip().lstrip("@")
    if not _TAG_RE.match(v):
        raise ValueError(f"Invalid tag '{v}' (letters, digits, '_', '.', ':', '-')")
    return v


def validate_folder(v: str) -> str:
    """Validate a folder path such as ``work`` or ``work/acme``."""
    v = v.strip().strip("/")
    parts = v.split("/")
    if not v or not all(_FOLDER_PART_RE.match(p) for p in parts):
        raise ValueError(
            f"Invalid folder '{v}' (letters, digits, '_', '.', '-'; '/' to nest)"
        )
    if len(parts) > MAX_FOLDER_DEPTH:
        raise ValueError(f"Folders can be nested at most {MAX_FOLDER_DEPTH} deep")
    return v


def format_local_forward(value: str) -> str:
    """Turn ``8080:localhost:80`` into ssh's ``8080 localhost:80`` form."""
    if " " in value.strip():
        return value
    parts = value.split(":")
    if len(parts) >= 3:
        return f"{':'.join(parts[:-2])} {':'.join(parts[-2:])}"
    return value


def format_path(path: Path) -> str:
    """Render a path for the config file, abbreviating the home directory."""
    home = Path.home()
    try:
        text = "~/" + str(path.relative_to(home))
    except ValueError:
        text = str(path)
    return quote(text)


class SSHConnection(BaseModel):
    """Model representing an SSH connection entry."""

    name: str
    hostname: str
    user: Optional[str] = None
    port: int = Field(default=22, ge=1, le=65535)
    identity_file: Optional[Path] = None
    proxy_jump: Optional[str] = None
    local_forward: Optional[str] = None
    extra_options: Dict[str, str] = Field(default_factory=dict)
    aliases: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    # Folder file (under AppConfig.folders_dir) holding the block; None = main config.
    folder: Optional[str] = None
    # File the Host block lives in (main config or an Include'd file).
    source: Optional[Path] = Field(default=None, exclude=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return validate_alias(v)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, v: List[str]) -> List[str]:
        return [validate_alias(a) for a in v]

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(validate_tag(t) for t in v))

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: Optional[str]) -> Optional[str]:
        return validate_folder(v) if v else None

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Hostname cannot be empty")
        v = v.strip()

        if len(v) > 253:
            raise ValueError("Hostname too long (max 253 characters)")

        # Lenient on purpose: IPv6, %h-style tokens and underscores are all
        # valid in ssh config. Reject whitespace and option-like values.
        if not _HOSTNAME_RE.match(v) or v.startswith("-"):
            raise ValueError(f"Invalid hostname: '{v}'")

        return v

    @field_validator("user")
    @classmethod
    def validate_user(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("User cannot be empty")
        return v.strip()

    @field_validator("identity_file")
    @classmethod
    def validate_identity_file(cls, v: Optional[Path]) -> Optional[Path]:
        if v is not None:
            # Expand user home directory
            expanded_path = Path(str(v)).expanduser()
            return expanded_path
        return v

    @property
    def target(self) -> str:
        """``user@hostname``, or just the hostname when no User is set."""
        return f"{self.user}@{self.hostname}" if self.user else self.hostname

    def to_config_string(self) -> str:
        """Convert the connection to SSH config format."""
        lines = [f"Host {' '.join([self.name, *self.aliases])}"]
        if self.tags:
            lines.append(f"    # sshm: tags={','.join(self.tags)}")
        lines.append(f"    HostName {self.hostname}")
        if self.user:
            lines.append(f"    User {self.user}")
        if self.port != 22:
            lines.append(f"    Port {self.port}")

        if self.identity_file:
            lines.append(f"    IdentityFile {format_path(self.identity_file)}")

        if self.proxy_jump:
            lines.append(f"    ProxyJump {self.proxy_jump}")

        if self.local_forward:
            lines.append(f"    LocalForward {format_local_forward(self.local_forward)}")

        for key, value in self.extra_options.items():
            lines.append(f"    {key} {value}")

        return "\n".join(lines)

    @classmethod
    def from_block(
        cls,
        block: Block,
        source: Optional[Path] = None,
        folder: Optional[str] = None,
    ) -> "SSHConnection":
        """Build a connection view over a parsed Host block."""
        patterns = block.patterns
        if not patterns:
            raise ValueError("Host name cannot be empty")

        tags = block.get_meta().get("tags", "")
        data: Dict[str, Any] = {
            "name": patterns[0],
            "aliases": patterns[1:],
            "hostname": patterns[0],
            "extra_options": {},
            "tags": [t for t in tags.split(",") if t],
            "folder": folder,
            "source": source,
        }

        seen = set()
        for line in block.options():
            key, value = line.key, line.value
            # ssh uses the first value obtained for each keyword
            if key in seen:
                continue
            seen.add(key)

            if key == "hostname":
                data["hostname"] = unquote(value)
            elif key == "user":
                data["user"] = unquote(value)
            elif key == "port":
                try:
                    data["port"] = int(value)
                except ValueError:
                    continue
            elif key == "identityfile":
                data["identity_file"] = Path(unquote(value)).expanduser()
            elif key == "proxyjump":
                data["proxy_jump"] = unquote(value)
            elif key == "localforward":
                data["local_forward"] = value
            else:
                data["extra_options"][line.keyword] = value

        return cls(**data)

    @classmethod
    def from_config_block(cls, config_block: str) -> "SSHConnection":
        """Create a connection from an SSH config block."""
        doc = SSHConfigDocument(config_block.strip() + "\n")
        if doc.preamble and any(not line.is_blank for line in doc.preamble):
            raise ValueError("Invalid SSH config block: must start with 'Host'")
        if not doc.blocks or doc.blocks[0].kind != "host":
            raise ValueError("Invalid SSH config block: must start with 'Host'")
        return cls.from_block(doc.blocks[0])


class AppConfig(BaseModel):
    """Model representing application configuration."""

    config_file: Path = Field(default=Path.home() / ".ssh" / "config")
    backup_dir: Path = Field(default=Path.home() / ".ssh" / "backups")
    folders_dir: Path = Field(default=Path.home() / ".ssh" / "sshm.d")
    default_key: Optional[Path] = None
    auto_backup: bool = True
    max_backups: int = Field(default=20, ge=0)
