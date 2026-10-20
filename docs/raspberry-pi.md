# Raspberry Pi kiosk installation

Use Raspberry Pi OS **32-bit Desktop or 64-bit Desktop**, **Bookworm or Trixie**,
on a Pi 4 with 2 GB RAM. A 32-bit installation does not need to be reimaged to
64-bit. A desktop is required for Chromium; Raspberry Pi OS Lite can run the server but
needs a separately installed and configured graphical session to show a kiosk.
Use a reliable power supply and microSD card. Select 1920 × 1080 landscape in the
desktop's display settings (1280 × 720 is also supported).

## Install this application independently

Do this once, as the normal account which will own this kiosk, **not as root**.
Use a directory without spaces, for example `/home/your-user/lake-conroe-kiosk`.
Python 3.11 or newer is required (Bookworm supplies 3.11; Trixie supplies 3.13).
Bullseye's default Python 3.9 is unsupported. This project's 32-bit target is
ARMv7/hard-float on Pi 4, not the ARMv6 original Pi / Pi Zero.

```sh
git clone https://github.com/BtCodex/lake-conroe-kiosk.git
cd lake-conroe-kiosk
./scripts/install-pi.sh --dry-run --install-packages --enable-server --install-kiosk-unit
./scripts/install-pi.sh --install-packages --install-kiosk-unit
# Check config/settings.local.json before enabling the server. If the sports
# scoreboard uses 8080, choose another free server.port, for example 8081.
./scripts/install-pi.sh --enable-server
```

The installer creates `.venv`, installs all pinned Python dependencies from
**binary wheels only**, copies
`config/settings.example.json` to `config/settings.local.json` **only if the local
file does not exist**, creates the application cache, and installs two distinctly
named units. The system server starts on boot; the user Chromium unit is only
installed, **not started or enabled**. Nothing disables, uninstalls, edits, or
renames your sports scoreboard. No desktop autologin or autostart files are changed.
Omit `--install-packages` if the packages are already installed. Omit
`--enable-server` for local development. Supply `LAKE_CONROE_CONFIG=/absolute/path`
to use a different configuration file (same path must be readable by the service).

### How 32-bit installation is supported

The same installer and configuration work on `armhf` (32-bit) and `arm64`
(64-bit); Debian's package manager selects the matching Chromium package.
There are no x86-only or aarch64-only downloads, Node.js runtime requirements,
or bundled browser binaries. All 16 runtime dependencies were downloaded
successfully as compatible wheels for **CPython 3.11 and 3.13 on ARMv7** during
release verification. `pydantic-core` is pinned to a version with ARMv7 wheels;
the other runtime wheels are architecture-independent. No Rust compiler or
source build is required. The installer checks Python before making changes and
uses `--only-binary=:all:` so a missing wheel fails instead of exhausting the Pi
while compiling. Do not remove that option to work around an installation error.

Check the installed userspace and Python rather than relying on `uname -m`
alone (a 32-bit userspace can run on a 64-bit kernel):

```sh
dpkg --print-architecture
python3 -c 'import struct, sys; print(sys.version); print(struct.calcsize("P") * 8, "bit Python")'
```

If pip reports no compatible wheel, confirm you are using the system CPython
from Bookworm/Trixie and that normal PyPI HTTPS access works. ARMv6 and old
Python versions are not supported. These dependency checks verify package
availability, not physical boot, HDMI, or hardware video decoding; complete the
on-device checks below on the actual Pi.

Keep the scoreboard on its existing port. A port collision will prevent this
server from binding; never stop an unrelated service to free the port. The
launcher requires the `lake-conroe-live` identity in the health response before
opening the display, so another service's JSON health endpoint is not accepted.

Inspect the server before selecting a display:

```sh
systemctl status lake-conroe-live.service
curl --fail http://127.0.0.1:8080/api/health
journalctl -u lake-conroe-live.service -n 60 --no-pager
```

The server can be healthy while individual external data sources are unavailable.
The health JSON reports each source separately. A network outage does not require
restarting Chromium: the display refreshes independent data sources and marks
cached information stale. Cached readings survive server restarts in `.cache`.

Edit `config/settings.local.json` for location, camera, polling intervals, units,
panel visibility, title, timezone, or port. Restart the server after editing:

```sh
sudo systemctl restart lake-conroe-live.service
```

The default bind address is loopback. If you intentionally expose this dashboard
to a trusted LAN, change `server.host`; do not expose it directly to the Internet.
The server is an unprivileged account, runs one Python process, and needs neither
a database nor cloud hosting. Do not use Chromium's `--no-sandbox` flag.

## Select the kiosk which owns the screen

Keep the scoreboard server running if desired. **Only one browser launcher should
own this desktop at boot.** First identify the scoreboard's existing startup
method and record its unit/desktop-autostart filename. Disable its *browser
launcher* when switching to Lake Conroe, using its documented procedure. Do not
guess service names, remove its files, or disable its data/server services.

For a scoreboard that already uses a user systemd browser unit, the explicit
switch is:

```sh
# Replace SCOREBOARD_BROWSER.service with the actual existing browser unit.
systemctl --user disable --now SCOREBOARD_BROWSER.service
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
systemctl --user start lake-conroe-kiosk.service
```

Run this from a terminal **inside the Pi desktop**, not a plain SSH shell. The
user service needs that desktop's Wayland/X11 socket environment; enabling a
service from SSH does not supply it. A missing display is logged and retried.
To return to the scoreboard:

```sh
systemctl --user stop lake-conroe-kiosk.service
# Also remove/comment the Lake Conroe autostart entry selected below.
systemctl --user enable --now SCOREBOARD_BROWSER.service
```

If the scoreboard uses a desktop autostart entry instead, preserve it and disable
it through the desktop's autostart manager (or comment only its browser command
in the relevant user file). Re-enable that same entry when switching back. Do
not leave both browser startup methods active.

## Desktop boot and automatic recovery

After choosing Lake Conroe, use Raspberry Pi Configuration / Control Centre
(or `sudo raspi-config`) to select **Desktop Autologin** for the intended account.
This is an explicit OS choice, and this project never makes it automatically.
After initial setup you can manage the machine over SSH. A monitor/display output
and an automatically logged-in desktop session are still needed to show Chromium.

Check the running desktop rather than assuming it from the OS release:

```sh
printf '%s\n' "$XDG_SESSION_TYPE" "$XDG_CURRENT_DESKTOP"
```

### Current Pi OS: Wayland / labwc (Bookworm or Trixie)

Pi OS's labwc session reads `~/.config/labwc/autostart`. Preserve its existing
contents and the scoreboard configuration. **If this user file does not exist**,
first copy `/etc/xdg/labwc/autostart` so creating a user override retains the
distribution's desktop startup. Never replace an existing user file:

```sh
mkdir -p ~/.config/labwc
if [ ! -e ~/.config/labwc/autostart ]; then
  cp /etc/xdg/labwc/autostart ~/.config/labwc/autostart
fi
```

After disabling the scoreboard's browser launch, append the following once to
that file with a text editor:

```sh
# BEGIN Lake Conroe Live (remove/comment this block to select another kiosk)
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP
systemctl --user start lake-conroe-kiosk.service
# END Lake Conroe Live
```

If `/etc/xdg/labwc/autostart` is absent, inspect your installed desktop's actual
session configuration instead of creating an incomplete override. Some older
Bookworm images use Wayfire; either select labwc in the OS configuration or use
that image's documented Wayfire autostart mechanism to run the same two commands.

In Raspberry Pi Control Centre / Configuration, turn **Screen Blanking off** for
the selected display session. On Wayland, `xset` is ineffective. If installed,
the launcher uses `wlopm --on '*'` to wake outputs, but this alone does not disable
the compositor's idle timer. The application also requests a browser Screen Wake
Lock where supported, and the launcher holds a session-scoped logind idle
inhibitor when permitted. The desktop blanking setting is the reliable fallback.

### Legacy desktop: X11 / LXDE

Install `x11-xserver-utils` if `xset` is absent. Preserve
`~/.config/lxsession/LXDE-pi/autostart`. If absent, copy the matching
`/etc/xdg/lxsession/LXDE-pi/autostart` first; do not replace an existing user file.
After disabling the scoreboard's browser command, append these lines once:

```text
@/bin/sh -c 'systemctl --user import-environment DISPLAY XAUTHORITY XDG_SESSION_TYPE XDG_CURRENT_DESKTOP; systemctl --user start lake-conroe-kiosk.service'
```

The launcher temporarily disables X11 screensaving and DPMS, restoring the
previous values when it exits. Use the OS's screen-blanking setting as a fallback.
Avoid editing both labwc and LXDE files unless you intentionally maintain both
sessions; only the active session's autostart runs.

### What restarts automatically

The system application unit restarts the backend after a crash. The user kiosk
unit restarts Chromium after a crash and waits for the local health endpoint
before opening it. Both use bounded delays rather than a tight restart loop.
Chromium uses its own profile under `~/.local/state/lake-conroe-live/chromium`,
separate from the scoreboard and your ordinary browser. Audio is muted by the
camera player; autoplay flags do not bypass provider embedding restrictions.

Reboot after setting the chosen desktop startup. Verify that the desktop logs
in, only the selected kiosk opens, the screen stays awake, and unplugging then
restoring the network recovers each source without rebooting the Pi. Actual Pi
boot, HDMI, power recovery, and accelerated video playback must be tested on the
physical device; cloud browser checks cannot verify those hardware behaviors.

## Troubleshooting and updates

```sh
systemctl --user status lake-conroe-kiosk.service
journalctl --user -u lake-conroe-kiosk.service -n 80 --no-pager
journalctl -u lake-conroe-live.service -f
```

If Chromium says there is no display, run the environment import inside the
desktop and check that the selected desktop's autostart is active. If video is
unavailable, verify the official source and provider embedding permission; do
not disable TLS verification or try to bypass player controls. Check `/api/health`
for unavailable upstreams. Browser LIVE status is based on actual player state.

To update, stop only these two services, preserve your local configuration, pull
the repository, rerun the installer without changing your desktop selection, and
restart them. You should review changes before deploying unattended hardware.
To stop using Lake Conroe, remove only its marked desktop autostart block, stop
its user service, and run `sudo systemctl disable --now lake-conroe-live.service`.
Re-enable your recorded scoreboard launcher; leave its configuration intact.
