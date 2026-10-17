"""Tags (comment metadata) and folders (Include'd files)."""

import pytest

from sshm.models import SSHConnection

BASE = """\
Host *.internal
    User admin

Host web
    HostName 10.0.0.1
    # keep me

Host db
    HostName 10.0.0.2
"""


class TestTags:
    def test_set_tags_writes_comment_ssh_ignores(self, make_manager):
        m = make_manager(BASE)
        m.set_tags("web", ["prod", "web"])
        assert "Host web\n    # sshm: tags=prod,web\n    HostName 10.0.0.1\n" in (
            m.config.config_file.read_text()
        )
        assert m.get_connection("web").tags == ["prod", "web"]

    def test_clearing_tags_restores_original_file(self, make_manager):
        m = make_manager(BASE)
        m.set_tags("web", ["prod"])
        m.set_tags("web", [])
        assert m.config.config_file.read_text() == BASE

    def test_filter_and_counts(self, make_manager):
        m = make_manager(BASE)
        m.set_tags("web", ["prod", "web"])
        m.set_tags("db", ["prod"])
        assert [c.name for c in m.list_connections(tags=["prod", "web"])] == ["web"]
        assert m.tag_counts() == {"prod": 2, "web": 1}

    def test_new_host_with_tags(self, make_manager):
        m = make_manager()
        m.add_connection(SSHConnection(name="a", hostname="x", tags=["@ops"]))
        assert m.get_connection("a").tags == ["ops"]

    def test_invalid_tag(self):
        with pytest.raises(ValueError, match="Invalid tag"):
            SSHConnection(name="a", hostname="x", tags=["no spaces"])


class TestFolders:
    def test_create_folder_adds_include_once(self, make_manager):
        m = make_manager(BASE)
        m.create_folder("work")
        m.create_folder("work/acme")
        text = m.config.config_file.read_text()
        assert text.count("Include ") == 1
        assert text.startswith("# sshm folders")
        assert text.endswith(BASE)
        assert m.folder_path("work/acme").is_file()
        assert m.folders() == ["work", "work/acme"]

    def test_add_into_folder(self, make_manager):
        m = make_manager(BASE)
        m.add_connection(SSHConnection(name="api", hostname="x", folder="work/acme"))
        assert "Host api" in m.folder_path("work/acme").read_text()
        assert "Host api" not in m.config.config_file.read_text()
        assert m.get_connection("api").folder == "work/acme"

    def test_move_keeps_block_verbatim_and_back(self, make_manager):
        m = make_manager(BASE)
        block = m.raw_block("web")
        m.move_connection("web", "work")
        assert m.get_connection("web").folder == "work"
        assert m.folder_path("work").read_text() == block + "\n"
        assert "Host web" not in m.config.config_file.read_text()

        m.move_connection("web", None)
        assert m.get_connection("web").folder is None
        assert m.raw_block("web") == block
        assert m.folder_path("work").read_text() == ""

    def test_list_by_folder(self, make_manager):
        m = make_manager(BASE)
        m.move_connection("web", "work/acme")
        assert [c.name for c in m.list_connections(folder="work")] == ["web"]
        assert [c.name for c in m.list_connections(folder="/")] == ["db"]

    def test_remove_folder_only_when_empty(self, make_manager):
        m = make_manager(BASE)
        m.move_connection("web", "work/acme")
        with pytest.raises(ValueError, match="not empty"):
            m.remove_folder("work/acme")
        m.move_connection("web", None)
        m.remove_folder("work/acme")
        assert not (m.config.folders_dir / "work").exists()

    @pytest.mark.parametrize("bad", ["../etc", "a/b/c/d", "a b", ".hidden"])
    def test_invalid_folder_names(self, make_manager, bad):
        with pytest.raises(ValueError):
            make_manager().folder_path(bad)

    def test_ssh_resolves_folder_hosts(self, make_manager):
        """The Include line sshm writes must be understood by real ssh."""
        import shutil
        import subprocess

        if shutil.which("ssh") is None:
            pytest.skip("ssh not installed")
        m = make_manager(BASE)
        m.add_connection(
            SSHConnection(name="api", hostname="10.9.9.9", user="me", folder="work")
        )
        out = subprocess.run(
            ["ssh", "-G", "-F", str(m.config.config_file), "api"],
            capture_output=True,
            text=True,
        ).stdout
        assert "hostname 10.9.9.9" in out
        assert "user me" in out
