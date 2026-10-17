# sshm

Manage, organize and connect to the hosts in your `~/.ssh/config` from the
terminal.

[![License](https://img.shields.io/github/license/palace22/sshm)](https://github.com/palace22/sshm/blob/main/LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/palace22/sshm/tests.yml)](https://github.com/palace22/sshm/actions)

```
█▀▀▀ █▀▀▀ █    ▄▄▄▄▄
 ▀▀▀█ ▀▀▀█ █▀▀█ █ █ █
  ▀▀▀▀ ▀▀▀▀ ▀  ▀ ▀ ▀ ▀
 ssh config manager :: v0.2.0 :: 53 hosts

> @prod db_
──────────────────────────────────────────────────────────────────
>* db-prod      postgres@10.0.0.2    work/acme  @prod @db
 * db-prod-ro   reader@10.0.0.3      work/acme  @prod @db

──────────────────────────────────────────────────────────────────
  2/53  2 marked   up/down move   tab mark   enter open 2 tabs   esc quit
  sshm --help all commands   sshm man manual   sshm add new host
```

- **Your SSH config stays the source of truth.** No database. Plain `ssh`
  keeps working, and sshm only adds things ssh already understands.
- **Lossless edits.** Only the lines you change are rewritten. Comments,
  formatting, repeated options, `Match` blocks, wildcard hosts and `Include`
  files stay exactly as they were.
- **Interactive picker.** Run `sshm`, type to fuzzy-filter, press enter or
  click. Recently used hosts come first.
- **Tabs.** Open several hosts at once, one tab each. Switch with a mouse
  click or `alt-left/right`. Tabs keep running after you detach.
- **Tags and folders.** Tags are labels (`@prod`, `@db`). Folders are real
  files under `~/.ssh/sshm.d/`.
- **Safe writes.** Atomic writes, the file mode is kept, symlinked configs
  (dotfile managers) keep working, and there are rotated automatic backups.

## Install

You need Python 3.10+ and the OpenSSH client. Tabs also need
[tmux](https://github.com/tmux/tmux) 3.0+ (`sudo dnf install tmux`,
`sudo apt install tmux`, `brew install tmux`). Everything else works without
it.

**Script** (uses pipx or uv if available, otherwise `pip --user`; also
installs the man page):

```bash
curl -fsSL https://raw.githubusercontent.com/palace22/sshm/main/install.sh | bash
```

**pipx** (recommended):

```bash
pipx install git+https://github.com/palace22/sshm.git
```

**uv**:

```bash
uv tool install git+https://github.com/palace22/sshm.git
```

Check that it works:

```bash
sshm --version
```

If `sshm` is not found, add `~/.local/bin` to your `PATH` (with pipx, run
`pipx ensurepath`), then open a new shell.

> Note: the `sshm` package on PyPI is a different project. Install from
> GitHub as shown above.

### Update

```bash
pipx reinstall sshm                     # pipx
uv tool install --reinstall git+https://github.com/palace22/sshm.git   # uv
curl -fsSL https://raw.githubusercontent.com/palace22/sshm/main/install.sh | bash   # script
```

Install a specific branch or tag with
`pipx install --force git+https://github.com/palace22/sshm.git@<ref>` or
`./install.sh --ref <ref>`.

### Uninstall

```bash
sshm man --uninstall       # if you ran 'sshm man --install'
pipx uninstall sshm        # or: uv tool uninstall sshm / ./install.sh --uninstall (does both)
```

Uninstalling leaves your `~/.ssh/config` alone. sshm's own settings live in
`~/.ssh-manager/`.

### Shell completion and man page

```bash
sshm --install-completion   # completes host, tag and folder names (restart the shell)
sshm man                    # the manual, always available
sshm man --install          # once, so plain 'man sshm' works too (install.sh does this)
```

## Try it without touching your real config

sshm reads its settings from the file named by `SSHM_CONFIG`. You can point it
at a copy of your config:

```bash
mkdir -p ~/sshm-try && cp ~/.ssh/config ~/sshm-try/config
cat > ~/sshm-try/settings.json <<EOF
{
  "config_file": "$HOME/sshm-try/config",
  "folders_dir": "$HOME/sshm-try/sshm.d",
  "backup_dir": "$HOME/sshm-try/backups"
}
EOF
export SSHM_CONFIG=~/sshm-try/settings.json

sshm list            # everything now reads and writes ~/sshm-try
unset SSHM_CONFIG    # back to the real ~/.ssh/config
```

## Using it

### Connect

```bash
sshm                      # picker: type to filter, enter to connect, esc to quit
sshm connect web          # by name or alias
sshm connect wbe          # typo: a single strong fuzzy match connects directly,
                          # otherwise the picker opens with "wbe" typed in
sshm connect @prod        # picker showing only hosts tagged prod
sshm connect /work        # picker showing only hosts in folder work (and below)
sshm connect web --dry-run               # print the ssh command
sshm connect web --extra-args "-L 8080:localhost:80 -v"
```

The picker uses the whole screen and gives it back when you leave.

| Key / mouse                  | Action                                         |
| ---------------------------- | ---------------------------------------------- |
| type                         | fuzzy filter (name, aliases, user, host, tags) |
| `@tag`, `/folder` in query   | only hosts with that tag / in that folder      |
| `up`/`down`, `ctrl-p`/`ctrl-n`, `pgup`/`pgdn`, wheel | move              |
| `tab`                        | mark/unmark the host (open several as tabs)    |
| `enter`, or click the selected row | connect, or open the marked hosts as tabs |
| click a row                  | select it                                      |
| `ctrl-u` / `ctrl-w`          | clear the query / delete a word                |
| `esc`, `ctrl-c`              | quit                                           |

sshm runs `ssh -- <alias>`, so ssh applies your whole config (`Host *`
defaults, `Match` blocks, includes). It adds `-F <file>` when you manage a file
other than `~/.ssh/config`.

### Tabs

You can open several connections at once, one tab per host:

```bash
sshm open web db api          # three tabs
sshm open @prod               # one tab per host tagged prod
sshm open /work               # every host in folder work
sshm                          # or mark hosts in the picker with tab, then enter
sshm tabs                     # come back to your tabs after detaching
sshm tabs --close             # close them all
```

```
 sshm   1 web   2 db   3 api  [ + ]        alt-</> switch  alt-n new  alt-w close  alt-d detach
 deploy@web:~$ _
```

| Key / mouse                      | Action                                        |
| -------------------------------- | --------------------------------------------- |
| click a tab, `alt-left/right`, `shift-left/right`, `alt-1`..`alt-9` | switch tabs |
| click `[ + ]`, `alt-n`           | new tab: opens the picker, the host you pick replaces it |
| `alt-w`                          | close the tab (asks first)                    |
| `alt-r`                          | reconnect a tab whose connection dropped      |
| `alt-d`                          | detach: tabs keep running, `sshm tabs` returns |
| mouse wheel                      | scroll back in a tab                          |

When a connection fails or drops, its tab stays open and shows
`connection closed`, so you can read the error and press `alt-r` to
reconnect.

The tabs run on sshm's own tmux server (`tmux -L sshm`), so your
`~/.tmux.conf` and your tmux sessions are not affected. If you run sshm inside
tmux, the hosts open as new windows of your current session instead. Some
terminals (VS Code's, for example) capture `alt` shortcuts: use the mouse,
`shift-left/right`, or tmux's normal `ctrl-b` keys there.

### List and inspect

```bash
sshm list                     # table; columns such as KEY/JUMP/TAGS appear only when used
sshm list --tag prod --tag db # hosts with both tags
sshm list --folder work       # hosts in work and its subfolders ('/' = main config)
sshm list --tree              # folder tree
sshm list --search 10.0.      # substring filter
sshm list --format json       # also: compact; --detailed for one panel per host
sshm show web                 # one host
sshm show web --raw           # the block exactly as written in the file
sshm search "deploy prod"     # ranked fuzzy search with scores
sshm test web                 # [ OK ] / [FAIL]: TCP check + non-interactive login
```

### Add, change, remove

```bash
sshm add                                   # interactive
sshm add --name web --hostname 10.0.0.1 --user deploy --port 2222 \
         --identity-file ~/.ssh/id_ed25519 --tag prod --folder work

sshm update web                            # interactive: enter keeps, '-' clears
sshm update web --hostname 10.0.0.9 --port 22
sshm update web --proxy-jump -             # '-' clears an optional field

sshm rename web web-old        # also renames aliases; ProxyJump references follow
sshm copy web web-staging      # clone with all options and comments
sshm remove web                # asks first; warns if other hosts jump through it
```

### Jump hosts and port forwarding

```bash
sshm add --name bastion --hostname 203.0.113.10 --user ec2-user \
         --identity-file ~/.ssh/bastion.pem
sshm add --name app --hostname 10.0.0.50 --user ubuntu \
         --proxy-jump bastion --local-forward 5432:localhost:5432
sshm connect app       # goes through bastion, localhost:5432 -> app:5432
```

### Tags

Tags are labels, and a host can have any number of them.

```bash
sshm tag add web prod frontend
sshm tag rm web frontend
sshm tag list                  # every tag with its host count
```

A tag is stored as a comment, which ssh ignores:

```
Host web
    # sshm: tags=prod,frontend
    HostName 10.0.0.1
```

### Folders

Folders are real files, and each host lives in exactly one place.

```bash
sshm folder add work           # creates ~/.ssh/sshm.d/work.conf
sshm folder add work/acme      # creates ~/.ssh/sshm.d/work/acme.conf (up to 3 levels)
sshm mv web work/acme          # moves the Host block, unchanged, into that file
sshm mv web /                  # back to ~/.ssh/config
sshm folder list               # tree of folders and hosts
sshm folder rm work/acme       # only when empty
```

The first time you create a folder, sshm adds one line at the top of
`~/.ssh/config`, so ssh loads every folder file:

```
# sshm folders (sshm folder --help)
Include ~/.ssh/sshm.d/*.conf ~/.ssh/sshm.d/*/*.conf ~/.ssh/sshm.d/*/*/*.conf
```

The folder files are ordinary ssh config files. You can edit them by hand,
keep them in git, or sync only `work/` to another machine.

### Export, import, backup

```bash
sshm export --output-file hosts.json      # includes tags and folders
sshm import hosts.json                    # skips names that already exist
sshm import hosts.json --overwrite
sshm backup                               # manual backup of config + folder files
```

Before writing a file, sshm saves a copy of it to `~/.ssh/backups/` and keeps
the last 20 (`max_backups`). Manual backups (`*.manual.bak`) are never
rotated. To restore a backup, copy it back over the file.

## Settings

```bash
sshm config show
sshm config set max_backups 50
sshm config set auto_backup false
sshm config set default_key ~/.ssh/id_ed25519   # suggested by 'sshm add'
```

| Key           | Default           | Meaning                                           |
| ------------- | ----------------- | ------------------------------------------------- |
| `config_file` | `~/.ssh/config`   | SSH config file to manage                         |
| `folders_dir` | `~/.ssh/sshm.d`   | Where folder files live                           |
| `backup_dir`  | `~/.ssh/backups`  | Automatic backups                                 |
| `auto_backup` | `true`            | Back up each file before writing it               |
| `max_backups` | `20`              | Automatic backups kept per file (`0` = unlimited) |
| `default_key` | none              | Identity file suggested by `sshm add`             |

Environment variables:

- `SSHM_CONFIG`: path of the settings file. Default: `~/.ssh-manager/config.json`.
- `SSHM_NO_ANIM=1`: turns off the logo sweep and typing effects. They are
  already off when output is piped.

## Development

```bash
git clone https://github.com/palace22/sshm.git && cd sshm
poetry install --with dev
poetry run sshm --help          # run from the checkout
poetry run pytest               # tests (they never touch your real ~/.ssh)
poetry run black sshm tests && poetry run isort sshm tests && poetry run mypy sshm
```

Layout:

| Path               | What it does                                                        |
| ------------------ | ------------------------------------------------------------------- |
| `sshm/sshconfig.py`| Lossless parser/renderer for ssh config files (`Include`, metadata) |
| `sshm/models.py`   | `SSHConnection` (a view over one Host block) and `AppConfig`        |
| `sshm/manager.py`  | Operations: list, add, update, move, tag, rename, backups, ssh cmd  |
| `sshm/tabs.py`     | Tabs on a private tmux server (generated config, mouse, keys)       |
| `sshm/cli/`        | Typer commands (`hosts`, `connect`, `organize`, `data`)             |
| `sshm/ui/`         | Tables, the picker, logo and terminal effects                       |

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
