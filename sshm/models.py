from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from pathlib import Path

class SSHConnection(BaseModel):
    """Model representing an SSH connection entry."""
    name: str
    hostname: str
    user: str
    port: int = Field(default=22)
    identity_file: Optional[Path] = None
    extra_options: Dict[str, str] = Field(default_factory=dict)

    def to_config_string(self) -> str:
        """Convert the connection to SSH config format."""
        lines = [f"Host {self.name}"]
        lines.append(f"    HostName {self.hostname}")
        lines.append(f"    User {self.user}")
        lines.append(f"    Port {self.port}")
        
        if self.identity_file:
            lines.append(f"    IdentityFile {self.identity_file}")
            
        for key, value in self.extra_options.items():
            lines.append(f"    {key} {value}")
            
        return "\n".join(lines) + "\n"

    @classmethod
    def from_config_block(cls, config_block: str) -> "SSHConnection":
        """Create a connection from an SSH config block."""
        lines = config_block.strip().split("\n")
        name = lines[0].split("Host", 1)[1].strip()
        
        data = {"name": name, "extra_options": {}}
        
        for line in lines[1:]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
                
            key, value = [x.strip() for x in line.split(maxsplit=1)]
            
            if key.lower() == "hostname":
                data["hostname"] = value
            elif key.lower() == "user":
                data["user"] = value
            elif key.lower() == "port":
                data["port"] = int(value)
            elif key.lower() == "identityfile":
                data["identity_file"] = Path(value)
            else:
                data["extra_options"][key] = value
                
        return cls(**data)

class AppConfig(BaseModel):
    """Model representing application configuration."""
    config_file: Path = Field(default=Path.home() / ".ssh" / "config")
    backup_dir: Path = Field(default=Path.home() / ".ssh" / "backups")
    default_key: Optional[Path] = None
    auto_backup: bool = True