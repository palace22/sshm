"""Remembers when each host was last connected to, for "recent first" ordering."""

import json
import time
from pathlib import Path
from typing import Dict, List

from .models import SSHConnection


class History:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Dict[str, float]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}

    def record(self, name: str) -> None:
        """Best effort: failing to save history must never block a connection."""
        data = self.load()
        data[name] = time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def sort(self, connections: List[SSHConnection]) -> List[SSHConnection]:
        """Most recently used first; never-used hosts keep their config order."""
        last = self.load()
        return sorted(connections, key=lambda c: -last.get(c.name, 0.0))
