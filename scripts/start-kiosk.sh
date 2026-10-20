#!/usr/bin/env bash
# Run inside the selected user's graphical desktop session, never as root.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if [ "$EUID" -eq 0 ]; then
  printf 'Chromium must run as a non-root desktop user.\n' >&2
  exit 1
fi
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  printf 'No graphical session. Import DISPLAY/WAYLAND_DISPLAY into the user service from desktop autostart.\n' >&2
  exit 1
fi

CONFIG_PATH=${LAKE_CONROE_CONFIG:-"$PROJECT_ROOT/config/settings.local.json"}
case "$CONFIG_PATH" in /*) ;; *) CONFIG_PATH="$PROJECT_ROOT/$CONFIG_PATH" ;; esac
if [ ! -f "$CONFIG_PATH" ]; then CONFIG_PATH="$PROJECT_ROOT/config/settings.example.json"; fi
PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON=$(command -v python3); fi
PORT=$(
  "$PYTHON" - "$CONFIG_PATH" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    config = json.load(source)
port = config.get("server", {}).get("port", 8080)
if not isinstance(port, int) or not 1 <= port <= 65535:
    raise SystemExit("Invalid dashboard port")
print(port)
PY
)
URL_CONFIG=$(
  "$PYTHON" - "${LAKE_CONROE_URL:-http://127.0.0.1:$PORT}" <<'PY'
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
parts = urlsplit(sys.argv[1])
if parts.scheme not in ("http", "https") or not parts.netloc:
    raise SystemExit("LAKE_CONROE_URL must be an HTTP(S) dashboard URL")
query = dict(parse_qsl(parts.query))
query["kiosk"] = "1"
print(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)))
print(urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + "/api/health", "", "")))
PY
)
mapfile -t URLS <<< "$URL_CONFIG"
DASHBOARD_URL=${URLS[0]}
HEALTH_URL=${LAKE_CONROE_HEALTH_URL:-"${URLS[1]}"}

"$PYTHON" - "$HEALTH_URL" <<'PY'
import json, sys, time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
            health = json.load(response)
            if response.status != 200 or not isinstance(health, dict) or health.get("application") != "lake-conroe-live":
                raise ValueError("Health endpoint is not Lake Conroe Live; check the configured port")
            break
    except Exception:
        if attempt == 59:
            raise SystemExit("Lake Conroe Live did not become ready; check the configured port and application service")
        time.sleep(2)
PY

BROWSER=''
for candidate in chromium chromium-browser; do
  if command -v "$candidate" >/dev/null; then BROWSER=$(command -v "$candidate"); break; fi
done
if [ -z "$BROWSER" ]; then printf 'Install Chromium first.\n' >&2; exit 1; fi

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/lake-conroe-live"
mkdir -p "$STATE_DIR/chromium"
BROWSER_PID=''
XSET_SAVED=''
cleanup() {
  if [ -n "$BROWSER_PID" ]; then kill "$BROWSER_PID" 2>/dev/null || true; fi
  if [ -n "$XSET_SAVED" ]; then
    # Restore the selected user's previous session settings when this kiosk exits.
    read -r screen_timeout screen_cycle dpms_enabled dpms_standby dpms_suspend dpms_off <<< "$XSET_SAVED"
    xset s "$screen_timeout" "$screen_cycle" >/dev/null 2>&1 || true
    if [ "$dpms_enabled" = Enabled ]; then
      xset +dpms >/dev/null 2>&1 || true
      xset dpms "$dpms_standby" "$dpms_suspend" "$dpms_off" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup EXIT
trap 'exit 0' TERM INT HUP

if [ "${XDG_SESSION_TYPE:-}" = x11 ] && command -v xset >/dev/null; then
  XSET_SAVED=$(xset q | awk '
    /timeout:/ {timeout=$2; cycle=$4}
    /DPMS is/ {enabled=$3}
    /Standby:/ {standby=$2; suspend=$4; off=$6}
    END {if (timeout != "") print timeout, cycle, enabled, standby, suspend, off}')
  xset s off >/dev/null 2>&1 || true
  xset -dpms >/dev/null 2>&1 || true
elif [ -n "${WAYLAND_DISPLAY:-}" ] && command -v wlopm >/dev/null; then
  # Wake existing Wayland outputs. Screen-blanking prevention is configured in
  # the Pi desktop, not by changing other kiosks or global compositor files.
  wlopm --on '*' >/dev/null 2>&1 || true
fi

BROWSER_ARGS=(
  --kiosk
  --no-first-run
  --no-default-browser-check
  --disable-session-crashed-bubble
  --autoplay-policy=no-user-gesture-required
  "--user-data-dir=$STATE_DIR/chromium"
  "$DASHBOARD_URL"
)
if [ -n "${WAYLAND_DISPLAY:-}" ]; then BROWSER_ARGS=(--ozone-platform=wayland "${BROWSER_ARGS[@]}"); fi

# An idle inhibitor is scoped to this browser process, not a system-wide setting.
if command -v systemd-inhibit >/dev/null && systemd-inhibit --what=idle --mode=block true 2>/dev/null; then
  systemd-inhibit --what=idle --who='Lake Conroe Live' --why='Selected kiosk display' --mode=block "$BROWSER" "${BROWSER_ARGS[@]}" &
else
  "$BROWSER" "${BROWSER_ARGS[@]}" &
fi
BROWSER_PID=$!
wait "$BROWSER_PID"
