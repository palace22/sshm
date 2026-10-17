#!/usr/bin/env bash
# Install or update sshm from GitHub. Running it again updates to the latest.
#
#   curl -fsSL https://raw.githubusercontent.com/palace22/sshm/main/install.sh | bash
#   ./install.sh [--ref BRANCH_OR_TAG] [--uninstall]
set -euo pipefail

REPO="palace22/sshm"
REF="main"
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ref) REF="$2"; shift 2 ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

info() { printf '\033[36m::\033[0m %s\n' "$1"; }
fail() { printf '\033[31m!!\033[0m %s\n' "$1" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

MAN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/man/man1"

if [[ "$ACTION" == "uninstall" ]]; then
    if has pipx && pipx list --short 2>/dev/null | grep -q '^sshm '; then
        pipx uninstall sshm
    elif has uv && uv tool list 2>/dev/null | grep -q '^sshm '; then
        uv tool uninstall sshm
    else
        python3 -m pip uninstall -y sshm
    fi
    rm -f "${MAN_DIR:?}/sshm.1"
    info "sshm uninstalled (settings in ~/.ssh-manager and your ~/.ssh/config are untouched)"
    exit 0
fi

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null \
    || fail "Python 3.10 or newer is required"

SPEC="git+https://github.com/${REPO}.git@${REF}"
if has pipx; then
    info "installing with pipx ($REF)"
    pipx install --force "$SPEC"
elif has uv; then
    info "installing with uv ($REF)"
    uv tool install --reinstall "$SPEC"
else
    info "pipx/uv not found, falling back to pip --user ($REF)"
    python3 -m pip install --user --upgrade --force-reinstall "$SPEC" \
        || fail "pip install failed. Install pipx (https://pipx.pypa.io) and re-run."
fi

if has sshm; then
    sshm man --install >/dev/null && info "man page installed: man sshm"
    SSHM_NO_ANIM=1 sshm --version
    info "done. Run 'sshm' to open the picker, 'sshm --help' for commands."
else
    info "installed, but 'sshm' is not on PATH yet: add ~/.local/bin to PATH"
    info "  (pipx users: run 'pipx ensurepath' and open a new shell)"
fi
