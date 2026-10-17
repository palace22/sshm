"""Tests for lossless SSH config parsing and surgical edits."""

from pathlib import Path

import pytest

from sshm.config import ConfigManager, parse_bool
from sshm.manager import SSHManager
from sshm.models import AppConfig, SSHConnection
from sshm.sshconfig import SSHConfigDocument

COMPLEX_CONFIG = """\
# Global settings
Include conf.d/*

Host web
    HostName 10.0.0.1
    User deploy
    LocalForward 8080 localhost:80
    LocalForward 9090 localhost:90
    # important comment

Host db db-alias
    HostName db.local

Host v6
    HostName 2001:db8::1

# describes nouser
Host nouser
    HostName nouser.example.com

Match host *.corp
    User corpuser

Host *
    ServerAliveInterval 30
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config"
    path.write_text(COMPLEX_CONFIG)
    return path


@pytest.fixture
def manager(config_file, tmp_path):
    return SSHManager(
        AppConfig(config_file=config_file, backup_dir=tmp_path / "backups")
    )


class TestDocument:
    @pytest.mark.parametrize(
        "text",
        [
            "",
            "\n\n",
            COMPLEX_CONFIG,
            COMPLEX_CONFIG.rstrip("\n"),  # no trailing newline
            COMPLEX_CONFIG.replace("\n", "\r\n"),  # CRLF
            "Host=a\n\tHostName=b\n  host   c  \n",
            "  # indented comment\nUser x\n",
        ],
    )
    def test_round_trip_is_byte_identical(self, text):
        assert SSHConfigDocument(text).render() == text

    def test_match_block_is_its_own_block(self):
        doc = SSHConfigDocument(COMPLEX_CONFIG)
        nouser = next(b for b in doc.blocks if b.patterns == ["nouser"])
        assert nouser.get("user") is None
        assert [b.kind for b in doc.blocks].count("match") == 1

    def test_comment_above_header_belongs_to_block(self):
        doc = SSHConfigDocument(COMPLEX_CONFIG)
        nouser = next(b for b in doc.blocks if b.patterns == ["nouser"])
        assert [line.text for line in nouser.leading] == ["# describes nouser"]

    def test_indented_trailing_comment_stays_in_body(self):
        doc = SSHConfigDocument(COMPLEX_CONFIG)
        web = next(b for b in doc.blocks if b.patterns == ["web"])
        assert "    # important comment\n" in [line.raw for line in web.body]

    def test_meta_round_trip(self):
        doc = SSHConfigDocument("Host a\n\tHostName x\n")
        block = doc.blocks[0]
        block.set_meta({"tags": "prod,web"})
        assert doc.render() == "Host a\n\t# sshm: tags=prod,web\n\tHostName x\n"
        assert block.get_meta() == {"tags": "prod,web"}
        block.set_meta({"tags": ""})
        assert doc.render() == "Host a\n\tHostName x\n"

    def test_set_preserves_keyword_spelling_and_separator(self):
        doc = SSHConfigDocument("Host a\n\thostname=old\n")
        doc.blocks[0].set("HostName", "new")
        assert doc.render() == "Host a\n\thostname=new\n"

    def test_insert_uses_block_indent_before_trailing_blank(self):
        doc = SSHConfigDocument("Host a\n\tHostName x\n\nHost b\n  HostName y\n")
        doc.blocks[0].set("User", "me")
        assert doc.render() == (
            "Host a\n\tHostName x\n\tUser me\n\nHost b\n  HostName y\n"
        )

    def test_append_block_without_trailing_newline(self):
        doc = SSHConfigDocument("Host a\n    HostName x")
        doc.append_block("Host b\n    HostName y")
        assert doc.render() == "Host a\n    HostName x\n\nHost b\n    HostName y\n"


class TestManagerRegressions:
    def test_lists_aliases_ipv6_and_hosts_without_user(self, manager):
        conns = {c.name: c for c in manager.list_connections()}
        assert set(conns) == {"web", "db", "v6", "nouser"}
        assert conns["db"].aliases == ["db-alias"]
        assert conns["v6"].hostname == "2001:db8::1"
        assert conns["nouser"].user is None
        assert conns["nouser"].extra_options == {}
        assert manager.warnings == []

    def test_noop_update_does_not_touch_file(self, manager, config_file):
        manager.update_connection("web", manager.get_connection("web"))
        assert config_file.read_text() == COMPLEX_CONFIG
        assert not list(manager.config.backup_dir.glob("*.bak"))

    def test_update_keeps_repeated_keys_and_comments(self, manager, config_file):
        web = manager.get_connection("web")
        manager.update_connection("web", web.model_copy(update={"user": "ops"}))
        text = config_file.read_text()
        assert text == COMPLEX_CONFIG.replace("User deploy", "User ops")

    def test_remove_keeps_following_match_block(self, manager, config_file):
        manager.remove_connection("nouser")
        text = config_file.read_text()
        assert "Match host *.corp\n    User corpuser\n" in text
        assert "nouser" not in text

    def test_remove_last_host_trims_blank_lines(self, tmp_path):
        path = tmp_path / "config"
        path.write_text("Host a\n    HostName x\n\nHost b\n    HostName y\n")
        m = SSHManager(AppConfig(config_file=path, backup_dir=tmp_path / "bk"))
        m.remove_connection("b")
        assert path.read_text() == "Host a\n    HostName x\n"

    def test_rename_alias_only_changes_alias(self, manager, config_file):
        manager.rename_connection("db-alias", "database")
        assert "Host db database\n" in config_file.read_text()

    def test_rename_pins_implicit_hostname(self, tmp_path):
        path = tmp_path / "config"
        path.write_text("Host box\n    User me\n")
        m = SSHManager(AppConfig(config_file=path, backup_dir=tmp_path / "bk"))
        m.rename_connection("box", "server")
        conn = m.get_connection("server")
        assert conn.hostname == "box"

    def test_rename_updates_proxy_jump_references(self, tmp_path):
        path = tmp_path / "config"
        path.write_text(
            "Host bastion\n    HostName b.example.com\n\n"
            "Host app\n    HostName 10.0.0.2\n    ProxyJump admin@bastion:2222\n"
        )
        m = SSHManager(AppConfig(config_file=path, backup_dir=tmp_path / "bk"))
        assert m.referrers("bastion") == ["app"]
        assert m.rename_connection("bastion", "jump") == ["app"]
        assert m.get_connection("app").proxy_jump == "admin@jump:2222"

    def test_rename_rejects_invalid_name(self, manager):
        with pytest.raises(ValueError, match="cannot contain"):
            manager.rename_connection("web", "a b")

    def test_copy_keeps_all_options(self, manager, config_file):
        manager.copy_connection("web", "web2")
        assert manager.raw_block("web2") == (
            "Host web2\n"
            "    HostName 10.0.0.1\n"
            "    User deploy\n"
            "    LocalForward 8080 localhost:80\n"
            "    LocalForward 9090 localhost:90\n"
            "    # important comment"
        )

    def test_hosts_from_include_files(self, manager, config_file):
        conf_d = config_file.parent / "conf.d"
        conf_d.mkdir()
        (conf_d / "work.conf").write_text("Host work\n    HostName w.local\n")
        text = COMPLEX_CONFIG.replace("Include conf.d/*", f"Include {conf_d}/*")
        config_file.write_text(text)

        work = manager.get_connection("work")
        assert work.source == conf_d / "work.conf"
        manager.update_connection("work", work.model_copy(update={"port": 2200}))
        assert "Port 2200" in (conf_d / "work.conf").read_text()
        assert config_file.read_text() == text

    def test_write_follows_symlink_and_keeps_mode(self, tmp_path):
        real = tmp_path / "dotfiles" / "config"
        real.parent.mkdir()
        real.write_text("Host a\n    HostName x\n")
        real.chmod(0o600)
        link = tmp_path / "config"
        link.symlink_to(real)

        m = SSHManager(AppConfig(config_file=link, backup_dir=tmp_path / "bk"))
        m.add_connection(SSHConnection(name="b", hostname="y"))

        assert link.is_symlink()
        assert "Host b" in real.read_text()
        assert real.stat().st_mode & 0o777 == 0o600

    def test_backups_are_rotated(self, tmp_path):
        path = tmp_path / "config"
        path.write_text("")
        bk = tmp_path / "bk"
        m = SSHManager(AppConfig(config_file=path, backup_dir=bk, max_backups=3))
        for i in range(6):
            m.add_connection(SSHConnection(name=f"h{i}", hostname="x"))
        assert len(list(bk.glob("config.*.bak"))) == 3

    def test_unparsable_host_is_reported_not_printed(self, tmp_path, capsys):
        path = tmp_path / "config"
        path.write_text("Host bad\n    HostName -oProxyCommand=x\n")
        m = SSHManager(AppConfig(config_file=path, backup_dir=tmp_path / "bk"))
        assert m.list_connections() == []
        assert capsys.readouterr().out == ""
        assert len(m.warnings) == 1 and "bad" in m.warnings[0]


class TestSshCommand:
    def test_connects_through_alias_with_custom_config(self, manager, config_file):
        conn = manager.get_connection("web")
        cmd = manager.ssh_command(conn, extra_args="-v -o 'SendEnv=A B'")
        assert cmd == [
            "ssh",
            "-F",
            str(config_file),
            "-v",
            "-o",
            "SendEnv=A B",
            "--",
            "web",
        ]


class TestAppSettings:
    @pytest.mark.parametrize(
        "text,expected", [("false", False), ("0", False), ("yes", True)]
    )
    def test_parse_bool(self, text, expected):
        assert parse_bool(text) is expected

    def test_set_auto_backup_false(self, tmp_path):
        cm = ConfigManager(tmp_path / "config.json")
        cm.set_setting("auto_backup", "false")
        assert cm.load_config().auto_backup is False

    def test_old_config_json_still_loads(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"config_file": "~/.ssh/config", "auto_backup": true}')
        cfg = ConfigManager(path).load_config()
        assert cfg.config_file == Path("~/.ssh/config").expanduser()
        assert cfg.max_backups == 20
