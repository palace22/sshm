"""Lossless, line-preserving model of an OpenSSH client config file.

The file is split into a preamble (everything before the first ``Host`` or
``Match`` line) followed by blocks. Every line keeps its original text and
line ending, so rendering an unmodified document reproduces the input byte
for byte. Edits only touch the lines they change.

sshm keeps its own metadata (tags) in a comment line that ssh ignores::

    Host web
        # sshm: tags=prod,web
        HostName 10.0.0.1
"""

import glob
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+$")
_OPTION_RE = re.compile(r"^(\s*)([^\s=#]+)(\s*=\s*|\s+)?(.*?)\s*$")

DEFAULT_INDENT = "    "
META_PREFIX = "sshm:"


def unquote(value: str) -> str:
    """Strip one pair of surrounding double quotes, as ssh does."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def quote(value: str) -> str:
    """Quote a single-argument value if it contains whitespace."""
    if any(c.isspace() for c in value) and not value.startswith('"'):
        return f'"{value}"'
    return value


class Line:
    """One physical line of a config file, including its line ending."""

    def __init__(self, raw: str):
        self.raw = raw

    @property
    def text(self) -> str:
        return self.raw.rstrip("\r\n")

    @property
    def ending(self) -> str:
        return self.raw[len(self.text) :]

    @property
    def is_blank(self) -> bool:
        return not self.text.strip()

    @property
    def is_comment(self) -> bool:
        return self.text.lstrip().startswith("#")

    @property
    def indent(self) -> str:
        return self.text[: len(self.text) - len(self.text.lstrip())]

    def _parts(self) -> Optional[Tuple[str, str, str, str]]:
        if self.is_blank or self.is_comment:
            return None
        m = _OPTION_RE.match(self.text)
        if not m:
            return None
        indent, keyword, sep, value = m.groups()
        return indent, keyword, sep or "", value

    @property
    def keyword(self) -> Optional[str]:
        """Keyword as written in the file (original spelling)."""
        parts = self._parts()
        return parts[1] if parts else None

    @property
    def key(self) -> Optional[str]:
        """Keyword, lower-cased (ssh keywords are case-insensitive)."""
        keyword = self.keyword
        return keyword.lower() if keyword else None

    @property
    def value(self) -> str:
        parts = self._parts()
        return parts[3] if parts else ""

    def set_value(self, value: str) -> None:
        """Replace the value, keeping indentation, keyword spelling and ending."""
        parts = self._parts()
        if parts is None:
            raise ValueError("Cannot set the value of a blank or comment line")
        indent, keyword, sep, _ = parts
        self.raw = f"{indent}{keyword}{sep or ' '}{value}{self.ending}"

    def ensure_ending(self, newline: str) -> None:
        if not self.ending:
            self.raw += newline


def split_lines(text: str) -> List[Line]:
    return [Line(raw) for raw in _LINE_RE.findall(text)]


class Block:
    """A ``Host`` or ``Match`` block.

    ``leading`` holds comment lines written directly above the header (no blank
    line in between, not indented deeper than the header). They describe the
    block and move or disappear with it.
    """

    def __init__(
        self,
        header: Line,
        body: Optional[List[Line]] = None,
        leading: Optional[List[Line]] = None,
        newline: str = "\n",
    ):
        self.header = header
        self.body: List[Line] = body or []
        self.leading: List[Line] = leading or []
        self.newline = newline

    @property
    def kind(self) -> str:
        return self.header.key or ""

    @property
    def patterns(self) -> List[str]:
        return [unquote(p) for p in self.header.value.split()]

    @property
    def is_concrete_host(self) -> bool:
        """True for a Host block whose patterns are all literal aliases."""
        if self.kind != "host" or not self.patterns:
            return False
        return not any("*" in p or "?" in p or p.startswith("!") for p in self.patterns)

    def lines(self) -> Iterator[Line]:
        yield from self.leading
        yield self.header
        yield from self.body

    def options(self) -> Iterator[Line]:
        return (line for line in self.body if line.key)

    def get(self, key: str) -> Optional[str]:
        """First value for ``key`` (ssh uses the first value it obtains)."""
        key = key.lower()
        for line in self.options():
            if line.key == key:
                return line.value
        return None

    def set(self, keyword: str, value: str) -> None:
        """Set the first occurrence of ``keyword``, or append it."""
        key = keyword.lower()
        for line in self.options():
            if line.key == key:
                line.set_value(value)
                return
        self._insert(f"{keyword} {value}")

    def unset(self, keyword: str) -> None:
        """Remove every occurrence of ``keyword``."""
        key = keyword.lower()
        self.body = [line for line in self.body if line.key != key]

    def set_patterns(self, patterns: List[str]) -> None:
        self.header.set_value(" ".join(patterns))

    def _meta_line(self) -> Optional[Line]:
        for line in self.body:
            if line.is_comment and line.text.lstrip()[1:].lstrip().startswith(
                META_PREFIX
            ):
                return line
        return None

    def get_meta(self) -> Dict[str, str]:
        """sshm metadata stored in the ``# sshm: key=value ...`` comment."""
        line = self._meta_line()
        if line is None:
            return {}
        text = line.text.lstrip()[1:].lstrip()[len(META_PREFIX) :]
        meta = {}
        for token in text.split():
            key, sep, value = token.partition("=")
            if sep:
                meta[key] = value
        return meta

    def set_meta(self, meta: Dict[str, str]) -> None:
        """Write the metadata comment (first body line); drop it when empty."""
        line = self._meta_line()
        pairs = " ".join(f"{k}={v}" for k, v in meta.items() if v)
        if not pairs:
            if line is not None:
                self.body.remove(line)
            return
        text = f"# {META_PREFIX} {pairs}"
        if line is not None:
            line.raw = f"{line.indent}{text}{line.ending}"
            return
        self.header.ensure_ending(self.newline)
        self.body.insert(0, Line(f"{self._option_indent()}{text}{self.newline}"))

    def strip_trailing_blanks(self) -> None:
        while self.body and self.body[-1].is_blank:
            self.body.pop()
        last = self.body[-1] if self.body else self.header
        last.ensure_ending(self.newline)

    def _option_indent(self) -> str:
        for line in self.options():
            return line.indent
        return DEFAULT_INDENT

    def _insert(self, text: str) -> None:
        pos = len(self.body)
        while pos > 0 and self.body[pos - 1].is_blank:
            pos -= 1
        anchor = self.body[pos - 1] if pos > 0 else self.header
        anchor.ensure_ending(self.newline)
        line = Line(f"{self._option_indent()}{text}{self.newline}")
        self.body.insert(pos, line)


class SSHConfigDocument:
    """A parsed SSH config file that can be edited and rendered losslessly."""

    def __init__(self, text: str = "", path: Optional[Path] = None):
        self.path = path
        self.original = text
        lines = split_lines(text)
        self.newline = "\r\n" if lines and lines[0].ending == "\r\n" else "\n"
        self.preamble: List[Line] = []
        self.blocks: List[Block] = []

        current = self.preamble
        for line in lines:
            if line.key in ("host", "match"):
                leading: List[Line] = []
                while (
                    current
                    and current[-1].is_comment
                    and len(current[-1].indent) <= len(line.indent)
                ):
                    leading.insert(0, current.pop())
                block = Block(line, leading=leading, newline=self.newline)
                self.blocks.append(block)
                current = block.body
            else:
                current.append(line)

    @classmethod
    def load(cls, path: Path) -> "SSHConfigDocument":
        if not path.exists():
            return cls("", path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Failed to read SSH config file {path}: {e}")
        return cls(text, path)

    def render(self) -> str:
        parts = [line.raw for line in self.preamble]
        for block in self.blocks:
            parts.extend(line.raw for line in block.lines())
        return "".join(parts)

    @property
    def is_modified(self) -> bool:
        return self.render() != self.original

    def host_blocks(self) -> Iterator[Block]:
        return (b for b in self.blocks if b.is_concrete_host)

    def all_lines(self) -> Iterator[Line]:
        yield from self.preamble
        for block in self.blocks:
            yield from block.lines()

    def include_patterns(self) -> List[str]:
        patterns: List[str] = []
        for line in self.all_lines():
            if line.key == "include":
                patterns.extend(unquote(p) for p in line.value.split())
        return patterns

    def _last_line(self) -> Optional[Line]:
        if self.blocks:
            block = self.blocks[-1]
            return block.body[-1] if block.body else block.header
        return self.preamble[-1] if self.preamble else None

    def append_block(self, text: str) -> Block:
        """Append a new block (given as config text) at the end of the file."""
        lines = [Line(line + self.newline) for line in text.strip("\n").split("\n")]
        block = Block(lines[0], body=lines[1:], newline=self.newline)
        self.append(block)
        return block

    def append(self, block: Block) -> None:
        """Append a block, separated from existing content by one blank line."""
        last = self._last_line()
        if last is not None:
            last.ensure_ending(self.newline)
            if not last.is_blank:
                container = self.blocks[-1].body if self.blocks else self.preamble
                container.append(Line(self.newline))
        block.newline = self.newline
        block.strip_trailing_blanks()
        self.blocks.append(block)

    def prepend(self, lines: List[str]) -> None:
        """Insert lines at the very top of the file, followed by a blank line."""
        new = [Line(text + self.newline) for text in lines]
        if self.preamble or self.blocks:
            new.append(Line(self.newline))
        self.preamble[:0] = new

    def remove_block(self, block: Block) -> None:
        index = self.blocks.index(block)
        del self.blocks[index]
        if index < len(self.blocks):
            return

        # Removed the last block: drop the blank lines it was separated by.
        container = self.blocks[-1].body if self.blocks else self.preamble
        while container and container[-1].is_blank:
            container.pop()
        last = self._last_line()
        if last is not None:
            last.ensure_ending(self.newline)


def resolve_includes(
    doc: SSHConfigDocument, base_dir: Path, _depth: int = 0
) -> List[SSHConfigDocument]:
    """Load every file pulled in by ``Include`` directives, recursively.

    Relative paths are resolved against ``base_dir`` (``~/.ssh`` for the user
    config, as ssh does). Glob results are sorted, matching glob(3).
    """
    if _depth > 16:
        return []
    found: List[SSHConfigDocument] = []
    for pattern in doc.include_patterns():
        expanded = Path(pattern).expanduser()
        if not expanded.is_absolute():
            expanded = base_dir / expanded
        for match in sorted(glob.glob(str(expanded))):
            path = Path(match)
            if not path.is_file():
                continue
            child = SSHConfigDocument.load(path)
            found.append(child)
            found.extend(resolve_includes(child, base_dir, _depth + 1))
    return found
