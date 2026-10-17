"""CLI smoke tests against a sandbox selected with SSHM_CONFIG."""

import json

from typer.testing import CliRunner

from sshm.cli import app

CONFIG = """\
Host web
    HostName 10.0.0.1
    User deploy
    ProxyJump bastion
    # keep me

Host bastion
    HostName b.example.com
"""

runner = CliRunner()


def run(*args, input=None):
    return runner.invoke(app, list(args), input=input)


def test_list_json(sandbox):
    sandbox.write_text(CONFIG)
    result = run("list", "--format", "json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [c["name"] for c in data] == ["web", "bastion"]
    assert data[1]["user"] is None


def test_show_raw_prints_block_verbatim(sandbox):
    sandbox.write_text(CONFIG)
    result = run("show", "web", "--raw")
    assert result.exit_code == 0
    assert "    # keep me" in result.output


def test_connect_dry_run_uses_alias(sandbox):
    sandbox.write_text(CONFIG)
    result = run("connect", "web", "--dry-run")
    assert result.exit_code == 0
    assert f"ssh -F {sandbox} -- web" in result.output


def test_update_can_clear_proxy_jump(sandbox):
    sandbox.write_text(CONFIG)
    result = run("update", "web", "--proxy-jump", "-")
    assert result.exit_code == 0, result.output
    text = sandbox.read_text()
    assert "ProxyJump" not in text
    assert "# keep me" in text


def test_remove_warns_about_jump_referrers(sandbox):
    sandbox.write_text(CONFIG)
    result = run("remove", "bastion", input="n\n")
    assert "Used as ProxyJump by: web" in result.output
    assert "Host bastion" in sandbox.read_text()


def test_unknown_host_is_a_clean_error(sandbox):
    sandbox.write_text(CONFIG)
    result = run("show", "nope")
    assert result.exit_code == 1
    assert "Connection 'nope' not found" in result.output
    assert "Traceback" not in result.output


def test_tags_and_folders_flow(sandbox):
    sandbox.write_text(CONFIG)
    assert run("tag", "add", "web", "prod", "web").exit_code == 0
    assert run("mv", "web", "work").exit_code == 0

    result = run("list", "--tag", "prod", "--format", "json")
    data = json.loads(result.output)
    assert [(c["name"], c["folder"], c["tags"]) for c in data] == [
        ("web", "work", ["prod", "web"])
    ]

    tree = run("list", "--tree").output
    assert "work/" in tree and "web" in tree
    assert "@prod" in run("tag", "list").output


def test_add_non_interactive_into_folder(sandbox):
    result = run(
        "add",
        "--name",
        "api",
        "--hostname",
        "10.1.1.1",
        "--user",
        "me",
        "--tag",
        "prod",
        "--folder",
        "work",
    )
    assert result.exit_code == 0, result.output
    assert "Host api" in (sandbox.parent / "sshm.d" / "work.conf").read_text()


def test_export_import_round_trip(sandbox, tmp_path):
    sandbox.write_text(CONFIG)
    run("tag", "add", "web", "prod")
    out = tmp_path / "export.json"
    assert run("export", "--output-file", str(out)).exit_code == 0
    sandbox.write_text("")
    result = run("import", str(out))
    assert result.exit_code == 0, result.output
    assert "2 imported" in result.output
    assert "# sshm: tags=prod" in sandbox.read_text()


def test_config_set_bool(sandbox):
    assert run("config", "set", "auto_backup", "false").exit_code == 0
    assert "auto_backup  False" in run("config", "show").output


def test_version(sandbox):
    result = run("--version")
    assert result.exit_code == 0
    assert "ssh config manager" in result.output


def test_bare_sshm_without_terminal_prints_help(sandbox):
    result = run()
    assert result.exit_code == 0
    assert "Usage:" in result.output and "connect" in result.output


def test_open_tabs_dry_run(sandbox):
    sandbox.write_text(CONFIG)
    run("tag", "add", "web", "prod")
    run("tag", "add", "bastion", "prod")
    result = run("open", "@prod", "web", "--dry-run")
    assert result.exit_code == 0, result.output
    assert result.output.count(f"ssh -F {sandbox} --") == 2  # web deduplicated


def test_open_unknown_tag(sandbox):
    sandbox.write_text(CONFIG)
    result = run("open", "@nope")
    assert result.exit_code == 1
    assert "No hosts match '@nope'" in result.output


def test_man_install_and_uninstall(sandbox, tmp_path, monkeypatch):
    from sshm.cli import data

    monkeypatch.setattr(data, "USER_MAN_DIR", tmp_path / "man1")
    assert run("man", "--install").exit_code == 0
    page = (tmp_path / "man1" / "sshm.1").read_text()
    assert page.startswith(".TH SSHM 1")
    assert run("man", "--uninstall").exit_code == 0
    assert not (tmp_path / "man1" / "sshm.1").exists()
