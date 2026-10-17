"""High-level operations on the SSH config: hosts, folders and tags."""

import os
import shlex
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError
from rapidfuzz import fuzz

from .models import (
    MAX_FOLDER_DEPTH,
    AppConfig,
    SSHConnection,
    format_local_forward,
    format_path,
    validate_alias,
    validate_folder,
)
from .sshconfig import Block, Line, SSHConfigDocument, quote, resolve_includes

SSH_DIR = Path.home() / ".ssh"
DEFAULT_CONFIG_FILE = SSH_DIR / "config"


@dataclass
class _Entry:
    doc: SSHConfigDocument
    block: Block
    conn: SSHConnection


def _sync(block: Block, keyword: str, old: Optional[str], new: Optional[str]) -> None:
    """Write ``new`` into the block only if it differs from ``old``."""
    if old == new:
        return
    if new:
        block.set(keyword, new)
    else:
        block.unset(keyword)


def _apply_changes(block: Block, old: SSHConnection, new: SSHConnection) -> None:
    """Apply the field-level diff between two connections to a Host block.

    Lines for unchanged fields are left untouched, so comments, repeated
    keywords (several LocalForward/IdentityFile lines) and formatting survive.
    """
    patterns = [new.name, *new.aliases]
    if patterns != [old.name, *old.aliases]:
        # Without a HostName line ssh connects to the alias itself; pin it
        # before renaming so the destination doesn't change.
        if block.get("hostname") is None and new.hostname == old.hostname:
            block.set("HostName", old.hostname)
        block.set_patterns(patterns)

    if new.tags != old.tags:
        block.set_meta({**block.get_meta(), "tags": ",".join(new.tags)})

    _sync(block, "HostName", old.hostname, new.hostname)
    _sync(block, "User", old.user, new.user)
    if new.port != old.port:
        block.set("Port", str(new.port))
    if new.identity_file != old.identity_file:
        if new.identity_file:
            block.set("IdentityFile", format_path(new.identity_file))
        else:
            block.unset("IdentityFile")
    _sync(block, "ProxyJump", old.proxy_jump, new.proxy_jump)
    if new.local_forward != old.local_forward:
        if new.local_forward:
            block.set("LocalForward", format_local_forward(new.local_forward))
        else:
            block.unset("LocalForward")

    for key in {**old.extra_options, **new.extra_options}:
        _sync(block, key, old.extra_options.get(key), new.extra_options.get(key))


def _jump_hosts(value: str) -> List[str]:
    """Host part of every hop in a ProxyJump value (``[user@]host[:port]``)."""
    hosts = []
    for hop in value.split(","):
        hop = hop.strip()
        if "://" in hop:
            hop = hop.split("://", 1)[1]
        hop = hop.rsplit("@", 1)[-1]
        if hop.startswith("["):
            hop = hop[1:].split("]", 1)[0]
        elif hop.count(":") == 1:
            hop = hop.split(":", 1)[0]
        hosts.append(hop)
    return hosts


def _rename_jump(value: str, old: str, new: str) -> str:
    hops = []
    for hop in value.split(","):
        if old in _jump_hosts(hop):
            prefix, sep, rest = hop.rpartition("@")
            hop = prefix + sep + rest.replace(old, new, 1)
        hops.append(hop)
    return ",".join(hops)


class SSHManager:
    def __init__(self, config: AppConfig):
        self.config = config
        # Non-fatal problems (unparsable hosts, failed backups), deduplicated.
        self.warnings: List[str] = []
        self.config.config_file.parent.mkdir(parents=True, exist_ok=True)

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    # ------------------------------------------------------------------ I/O

    def backup(
        self,
        path: Optional[Path] = None,
        dest_dir: Optional[Path] = None,
        manual: bool = False,
    ) -> Optional[Path]:
        """Copy a config file into the backup dir and return the copy's path.

        Automatic backups are rotated (``max_backups``); manual ones are kept.
        """
        path = path or self.config.config_file
        if not path.exists():
            return None

        backup_dir = dest_dir or self.config.backup_dir
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        kind = ".manual" if manual else ""
        backup_file = backup_dir / f"{path.name}.{timestamp}{kind}.bak"
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup_file.write_bytes(path.read_bytes())
        os.chmod(backup_file, 0o600)

        if not manual and self.config.max_backups:
            backups = sorted(
                b
                for b in backup_dir.glob(f"{path.name}.*.bak")
                if not b.name.endswith(".manual.bak")
            )
            for old in backups[: -self.config.max_backups]:
                old.unlink(missing_ok=True)
        return backup_file

    def _write_doc(self, doc: SSHConfigDocument) -> None:
        """Atomically write a document back to its file.

        Symlinks (dotfile managers) are followed so the link itself survives,
        and the original file mode is kept (0600 for new files).
        """
        assert doc.path is not None
        if not doc.is_modified and doc.path.exists():
            return
        target = doc.path.resolve()

        if self.config.auto_backup:
            try:
                self.backup(target)
            except OSError as e:
                self._warn(f"Failed to create backup: {e}")

        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(doc.render())
            os.chmod(tmp, mode)
            os.replace(tmp, target)
        except OSError as e:
            Path(tmp).unlink(missing_ok=True)
            raise ValueError(f"Failed to write SSH config file: {e}")
        doc.original = doc.render()

    def _main_doc(self) -> SSHConfigDocument:
        return SSHConfigDocument.load(self.config.config_file)

    def _load_docs(self) -> List[SSHConfigDocument]:
        main = self._main_doc()
        docs = [main]
        # Relative Include paths are relative to ~/.ssh, even with ssh -F.
        for child in resolve_includes(main, SSH_DIR):
            if all(child.path != d.path for d in docs):
                docs.append(child)
        return docs

    def _entries(self) -> Tuple[List[SSHConfigDocument], List[_Entry]]:
        docs = self._load_docs()
        entries: List[_Entry] = []
        seen = set()
        for doc in docs:
            folder = self._folder_of(doc.path)
            for block in doc.host_blocks():
                name = block.patterns[0]
                if name in seen:
                    # ssh merges duplicate blocks; first one wins, like ssh.
                    self._warn(f"Duplicate host '{name}' in {doc.path} ignored")
                    continue
                try:
                    conn = SSHConnection.from_block(block, doc.path, folder)
                except ValidationError as e:
                    err = e.errors()[0]
                    field = ".".join(str(part) for part in err["loc"])
                    self._warn(
                        f"Skipped host '{' '.join(block.patterns)}' "
                        f"({doc.path}): {field}: {err['msg']}"
                    )
                    continue
                seen.add(name)
                entries.append(_Entry(doc, block, conn))
        return docs, entries

    def _find(self, entries: List[_Entry], name: str) -> _Entry:
        for entry in entries:
            if entry.conn.name == name:
                return entry
        for entry in entries:
            if name in entry.conn.aliases:
                return entry
        raise ValueError(f"Connection '{name}' not found")

    @staticmethod
    def _taken(
        entries: List[_Entry], name: str, exclude: Optional[_Entry] = None
    ) -> bool:
        return any(
            e is not exclude and (e.conn.name == name or name in e.conn.aliases)
            for e in entries
        )

    # -------------------------------------------------------------- folders

    def folder_path(self, folder: str) -> Path:
        return self.config.folders_dir / f"{validate_folder(folder)}.conf"

    def _folder_of(self, path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        try:
            rel = path.resolve().relative_to(self.config.folders_dir.resolve())
        except ValueError:
            return None
        return rel.with_suffix("").as_posix() if rel.suffix == ".conf" else None

    def _folder_include_patterns(self) -> List[str]:
        base = format_path(self.config.folders_dir).strip('"')
        return [f"{base}/{'*/' * depth}*.conf" for depth in range(MAX_FOLDER_DEPTH)]

    def _ensure_folder_include(self) -> None:
        """Add the ``Include`` line for folder files to the top of the config."""
        main = self._main_doc()
        patterns = self._folder_include_patterns()
        if patterns[0] in main.include_patterns():
            return
        main.prepend(
            [
                "# sshm folders (sshm folder --help)",
                "Include " + " ".join(quote(p) for p in patterns),
            ]
        )
        self._write_doc(main)

    def folders(self) -> List[str]:
        """Every folder that has a file, sorted."""
        root = self.config.folders_dir
        if not root.is_dir():
            return []
        found = []
        for path in root.rglob("*.conf"):
            folder = self._folder_of(path)
            if folder and folder.count("/") < MAX_FOLDER_DEPTH:
                found.append(folder)
        return sorted(found)

    def create_folder(self, folder: str) -> Path:
        path = self.folder_path(folder)
        if not path.exists():
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.touch(mode=0o600)
        self._ensure_folder_include()
        return path

    def remove_folder(self, folder: str) -> None:
        """Delete an empty folder file (and empty parent directories)."""
        path = self.folder_path(folder)
        if not path.exists():
            raise ValueError(f"Folder '{folder}' not found")
        if SSHConfigDocument.load(path).blocks:
            raise ValueError(
                f"Folder '{folder}' is not empty; move its hosts out first"
            )
        path.unlink()
        parent = path.parent
        root = self.config.folders_dir.resolve()
        while parent.resolve() != root and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def _target_doc(
        self, docs: List[SSHConfigDocument], folder: Optional[str]
    ) -> SSHConfigDocument:
        if not folder:
            return docs[0]
        path = self.folder_path(folder)
        for doc in docs:
            if doc.path is not None and doc.path.resolve() == path.resolve():
                return doc
        return SSHConfigDocument.load(path)

    # --------------------------------------------------------------- search

    def _composite_key(self, conn: SSHConnection) -> str:
        """Build a composite search string for a connection."""
        parts = [conn.name, *conn.aliases, conn.user or "", conn.hostname, *conn.tags]
        return " ".join(parts)

    def score(self, search_term: str, conn: SSHConnection) -> int:
        """Score a connection against a search term using multiple strategies.

        WRatio on the names, partial_ratio (substring) and token_set_ratio
        (word order agnostic) on name + aliases + user + hostname + tags.
        """
        composite = self._composite_key(conn)
        s1 = max(fuzz.WRatio(search_term, n) for n in [conn.name, *conn.aliases])
        s2 = fuzz.partial_ratio(search_term, composite)
        s3 = fuzz.token_set_ratio(search_term, composite)
        return int(max(s1, s2 * 0.9, s3 * 0.95))

    def list_connections(
        self,
        search: Optional[str] = None,
        tags: Sequence[str] = (),
        folder: Optional[str] = None,
    ) -> List[SSHConnection]:
        """List connections, filtered by substring, tags (all must match) and folder.

        ``folder`` also matches its subfolders; ``"/"`` means the main config.
        """
        _, entries = self._entries()
        connections = [e.conn for e in entries]

        if search:
            needle = search.lower()
            connections = [
                c for c in connections if needle in self._composite_key(c).lower()
            ]
        for tag in tags:
            tag = tag.lstrip("@")
            connections = [c for c in connections if tag in c.tags]
        if folder == "/":
            connections = [c for c in connections if c.folder is None]
        elif folder:
            prefix = folder.strip("/")
            connections = [
                c
                for c in connections
                if c.folder and (c.folder + "/").startswith(prefix + "/")
            ]
        return connections

    def get_connection(self, name: str) -> SSHConnection:
        """Get a specific SSH connection by exact name or alias."""
        _, entries = self._entries()
        return self._find(entries, name).conn

    def raw_block(self, name: str) -> str:
        """The Host block exactly as written in the config file."""
        _, entries = self._entries()
        block = self._find(entries, name).block
        return "".join(line.raw for line in block.lines()).rstrip("\r\n")

    def find_best_matches(
        self, search_term: str, limit: int = 5
    ) -> List[Tuple[SSHConnection, int]]:
        """Best fuzzy matches for ``search_term``, highest score first."""
        scored = [(c, self.score(search_term, c)) for c in self.list_connections()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def referrers(self, name: str) -> List[str]:
        """Names of connections that use ``name`` as a ProxyJump hop."""
        _, entries = self._entries()
        return [
            e.conn.name
            for e in entries
            if e.conn.proxy_jump and name in _jump_hosts(e.conn.proxy_jump)
        ]

    def tag_counts(self) -> Dict[str, int]:
        counts = Counter(t for c in self.list_connections() for t in c.tags)
        return dict(sorted(counts.items()))

    # ------------------------------------------------------------- mutation

    def add_connection(self, connection: SSHConnection) -> None:
        """Add a new connection at the end of the main config or its folder file."""
        if connection.folder:
            self.create_folder(connection.folder)
        docs, entries = self._entries()
        for name in [connection.name, *connection.aliases]:
            if self._taken(entries, name):
                raise ValueError(f"Connection '{name}' already exists")

        doc = self._target_doc(docs, connection.folder)
        doc.append_block(connection.to_config_string())
        self._write_doc(doc)

    def update_connection(self, name: str, connection: SSHConnection) -> None:
        """Update an existing SSH connection.

        'name' is the current connection name. connection.name may differ
        if a rename is desired (the Host line will be updated accordingly).
        Only the lines of fields that actually changed are rewritten; a
        different ``folder`` moves the block to that folder's file.
        """
        if connection.folder:
            # Before loading: this may add the folder Include to the main config.
            self.create_folder(connection.folder)
        docs, entries = self._entries()
        entry = self._find(entries, name)
        for new_name in [connection.name, *connection.aliases]:
            if self._taken(entries, new_name, exclude=entry):
                raise ValueError(f"Connection '{new_name}' already exists")

        _apply_changes(entry.block, entry.conn, connection)
        if connection.folder == entry.conn.folder:
            self._write_doc(entry.doc)
            return

        target = self._target_doc(docs, connection.folder)
        entry.doc.remove_block(entry.block)
        target.append(entry.block)
        self._write_doc(target)
        self._write_doc(entry.doc)

    def move_connection(self, name: str, folder: Optional[str]) -> None:
        """Move a host into ``folder`` (None = main config)."""
        conn = self.get_connection(name)
        self.update_connection(name, conn.model_copy(update={"folder": folder}))

    def set_tags(self, name: str, tags: List[str]) -> SSHConnection:
        conn = self.get_connection(name)
        updated = SSHConnection(**{**conn.model_dump(), "tags": tags})
        self.update_connection(name, updated)
        return updated

    def remove_connection(self, name: str) -> None:
        """Remove an SSH connection."""
        _, entries = self._entries()
        entry = self._find(entries, name)
        entry.doc.remove_block(entry.block)
        self._write_doc(entry.doc)

    def rename_connection(self, old_name: str, new_name: str) -> List[str]:
        """Rename a connection (or one of its aliases) in place.

        ProxyJump references to the old name in other hosts are updated too.
        Returns the names of the connections whose ProxyJump was rewritten.
        """
        new_name = validate_alias(new_name)
        _, entries = self._entries()
        entry = self._find(entries, old_name)
        if self._taken(entries, new_name, exclude=entry):
            raise ValueError(f"Connection '{new_name}' already exists")

        if old_name == entry.conn.name:
            renamed = entry.conn.model_copy(update={"name": new_name})
        else:
            aliases = [new_name if a == old_name else a for a in entry.conn.aliases]
            renamed = entry.conn.model_copy(update={"aliases": aliases})
        _apply_changes(entry.block, entry.conn, renamed)
        dirty = {id(entry.doc): entry.doc}

        updated = []
        for other in entries:
            jump = other.conn.proxy_jump
            if other is entry or not jump or old_name not in _jump_hosts(jump):
                continue
            other.block.set("ProxyJump", _rename_jump(jump, old_name, new_name))
            dirty[id(other.doc)] = other.doc
            updated.append(other.conn.name)

        for doc in dirty.values():
            self._write_doc(doc)
        return updated

    def copy_connection(self, source_name: str, new_name: str) -> None:
        """Clone a connection under a new name, keeping every option and comment.

        The copy is placed in the same file as the source.
        """
        new_name = validate_alias(new_name)
        _, entries = self._entries()
        source = self._find(entries, source_name)
        if self._taken(entries, new_name):
            raise ValueError(f"Connection '{new_name}' already exists")

        header = Line(source.block.header.text)
        header.set_value(new_name)
        body = [line.text for line in source.block.body]
        if source.block.get("hostname") is None:
            body.insert(0, f"    HostName {source.conn.hostname}")

        source.doc.append_block("\n".join([header.text, *body]))
        self._write_doc(source.doc)

    # ------------------------------------------------------------------ ssh

    def ssh_command(
        self,
        connection: SSHConnection,
        extra_args: Optional[str] = None,
        options: Sequence[str] = (),
        remote_command: Sequence[str] = (),
    ) -> List[str]:
        """Build the ssh invocation for a connection.

        ssh is pointed at the Host alias so it resolves the full config
        itself (Host patterns, Match blocks, Include files, repeated options).
        """
        cmd = ["ssh"]
        if self.config.config_file.resolve() != DEFAULT_CONFIG_FILE.resolve():
            cmd.extend(["-F", str(self.config.config_file)])
        for option in options:
            cmd.extend(["-o", option])
        if extra_args:
            cmd.extend(shlex.split(extra_args, posix=os.name != "nt"))
        cmd.extend(["--", connection.name])
        cmd.extend(remote_command)
        return cmd
