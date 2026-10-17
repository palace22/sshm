"""Tabs on a throwaway tmux server (skipped when tmux is missing)."""

import os
import subprocess
from pathlib import Path

import pytest

from sshm.tabs import SESSION, Tab, TabSession, tmux_version

pytestmark = pytest.mark.skipif(tmux_version() is None, reason="tmux not installed")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    socket = f"sshm-test-{os.getpid()}"
    yield TabSession(tmp_path / "tmux.conf", socket=socket)
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
    tmpdir = Path(os.environ.get("TMUX_TMPDIR", "/tmp"))
    (tmpdir / f"tmux-{os.getuid()}" / socket).unlink(missing_ok=True)


def tmux(session, *args):
    return subprocess.run(
        ["tmux", "-L", session.socket, *args], capture_output=True, text=True
    )


def test_open_creates_named_tabs_and_adds_more(session):
    assert session.open([Tab("web", ["sleep", "60"]), Tab("db", ["sleep", "60"])])
    assert session.windows() == ["web", "db"]
    assert tmux(session, "display", "-p", "-t", SESSION, "#W").stdout.strip() == "web"

    session.open([Tab("api", ["sleep", "60"])])
    assert session.windows() == ["web", "db", "api"]
    # The newly opened tab becomes the current one.
    assert tmux(session, "display", "-p", "-t", SESSION, "#W").stdout.strip() == "api"


def test_generated_config_loads_cleanly(session):
    session.open([Tab("web", ["sleep", "60"])])
    result = tmux(session, "source-file", str(session.conf_path))
    assert result.returncode == 0, result.stderr
    assert tmux(session, "show", "-gv", "mouse").stdout.strip() == "on"
    keys = tmux(session, "list-keys", "-T", "root").stdout
    for key in ("M-Left", "M-Right", "M-n", "M-w", "M-r", "M-d", "MouseDown1Status"):
        assert key in keys


def test_tabs_carry_sshm_environment(session, monkeypatch):
    monkeypatch.setenv("SSHM_CONFIG", "/tmp/sshm-settings.json")
    session.open([Tab("web", ["sleep", "60"])])
    env = tmux(session, "show-environment", "-t", SESSION).stdout
    assert "SSHM_TABS=1" in env
    assert "SSHM_CONFIG=/tmp/sshm-settings.json" in env


def test_close(session):
    session.open([Tab("web", ["sleep", "60"])])
    session.close()
    assert not session.exists()
