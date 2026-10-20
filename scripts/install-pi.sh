#!/usr/bin/env bash
# Run as the intended desktop/server user, not root. Nothing else is disabled.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
INSTALL_PACKAGES=false
ENABLE_SERVER=false
INSTALL_KIOSK=false
DRY_RUN=false

usage() {
  cat <<'HELP'
Usage: ./scripts/install-pi.sh [options]
  --install-packages    Install Python venv and Chromium using apt (sudo).
  --enable-server       Install, enable, and start only lake-conroe-live.service.
  --install-kiosk-unit  Install a user unit; do not enable or start Chromium.
  --dry-run             Show actions without changing files or services.
  --help                Show this help.

With no options, creates/updates .venv and local configuration only.
Never modifies another kiosk, desktop autostart, or OS login configuration.
HELP
}

for argument in "$@"; do
  case "$argument" in
    --install-packages) INSTALL_PACKAGES=true ;;
    --enable-server) ENABLE_SERVER=true ;;
    --install-kiosk-unit) INSTALL_KIOSK=true ;;
    --dry-run) DRY_RUN=true ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$EUID" -eq 0 ]; then
  printf 'Run this script as the intended non-root kiosk user; sudo is used only for apt/system service installation.\n' >&2
  exit 1
fi

# systemd interprets percent, dollar, and shell-like escapes. Restrict installation
# paths rather than generating subtly ambiguous units. Ordinary Pi paths work.
case "$PROJECT_ROOT" in
  *[!a-zA-Z0-9_./-]*)
    printf 'Use a checkout path containing only letters, digits, underscore, dot, slash, or hyphen.\n' >&2
    exit 1 ;;
esac

command -v python3 >/dev/null || { printf 'Python 3.11+ is required (Raspberry Pi OS Bookworm/Trixie Desktop, 32-bit or 64-bit).\n' >&2; exit 1; }
python3 - <<'PY'
import struct
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11+ is required. Use Raspberry Pi OS Bookworm/Trixie Desktop (32-bit or 64-bit); Bullseye Python 3.9 is unsupported.')
print(f'Python {sys.version_info.major}.{sys.version_info.minor}, {struct.calcsize("P") * 8}-bit interpreter')
PY

run() {
  if "$DRY_RUN"; then
    printf 'Would run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if "$INSTALL_PACKAGES"; then
  command -v apt-get >/dev/null || { printf 'This option requires Raspberry Pi OS/Debian apt.\n' >&2; exit 1; }
  run sudo apt-get update
  # Current Pi OS uses chromium; older images may use chromium-browser.
  BROWSER_PACKAGE=chromium
  if ! apt-cache show chromium >/dev/null 2>&1 && apt-cache show chromium-browser >/dev/null 2>&1; then
    BROWSER_PACKAGE=chromium-browser
  fi
  run sudo apt-get install -y --no-install-recommends python3-venv "$BROWSER_PACKAGE"
  if [ "${XDG_SESSION_TYPE:-}" = x11 ]; then
    run sudo apt-get install -y --no-install-recommends x11-xserver-utils
  fi
fi

run python3 -m venv "$PROJECT_ROOT/.venv"
# Pydantic-core has ARMv7 wheels for the supported Pi OS Python versions.
# Fail clearly instead of compiling Rust on a 2 GB Pi if a wheel is unavailable.
run "$PROJECT_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check --only-binary=:all: -r "$PROJECT_ROOT/requirements.txt"
run mkdir -p "$PROJECT_ROOT/.cache/lake-conroe-live"
CONFIG_PATH=${LAKE_CONROE_CONFIG:-"$PROJECT_ROOT/config/settings.local.json"}
case "$CONFIG_PATH" in
  /*) ;;
  *) CONFIG_PATH="$PROJECT_ROOT/$CONFIG_PATH" ;;
esac
case "$CONFIG_PATH" in
  *[!a-zA-Z0-9_./-]*) printf 'Configuration path contains unsupported systemd characters.\n' >&2; exit 1 ;;
esac
if [ ! -e "$CONFIG_PATH" ]; then
  run mkdir -p "$(dirname -- "$CONFIG_PATH")"
  run cp --no-clobber "$PROJECT_ROOT/config/settings.example.json" "$CONFIG_PATH"
fi

render_unit() {
  local source=$1 destination=$2
  python3 - "$source" "$destination" "$PROJECT_ROOT" "$CONFIG_PATH" "$(id -un)" "$(id -gn)" <<'PY'
from pathlib import Path
import sys
source, destination, root, config, user, group = sys.argv[1:]
text = Path(source).read_text()
for key, value in {"ROOT": root, "CONFIG": config, "USER": user, "GROUP": group}.items():
    text = text.replace("@" + key + "@", value)
Path(destination).write_text(text)
PY
}

if "$ENABLE_SERVER"; then
  if "$DRY_RUN"; then
    printf 'Would render deploy/lake-conroe-live.service for user %s into /etc/systemd/system/.\n' "$(id -un)"
  else
    UNIT_TMP=$(mktemp)
    trap 'rm -f -- "$UNIT_TMP"' EXIT
    render_unit "$PROJECT_ROOT/deploy/lake-conroe-live.service" "$UNIT_TMP"
    sudo install -m 0644 "$UNIT_TMP" /etc/systemd/system/lake-conroe-live.service
    rm -f -- "$UNIT_TMP"
    trap - EXIT
  fi
  run sudo systemctl daemon-reload
  run sudo systemctl enable --now lake-conroe-live.service
fi

if "$INSTALL_KIOSK"; then
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  run mkdir -p "$UNIT_DIR"
  if "$DRY_RUN"; then
    printf 'Would render deploy/lake-conroe-kiosk.service into %s.\n' "$UNIT_DIR"
  else
    render_unit "$PROJECT_ROOT/deploy/lake-conroe-kiosk.service" "$UNIT_DIR/lake-conroe-kiosk.service"
    chmod 0644 "$UNIT_DIR/lake-conroe-kiosk.service"
  fi
  run systemctl --user daemon-reload
  printf 'Kiosk unit installed only. Select a desktop startup method in docs/raspberry-pi.md.\n'
fi

printf 'Setup complete%s. Your other kiosks and OS login settings were not changed.\n' "$(if "$DRY_RUN"; then printf ' (dry run)'; fi)"
