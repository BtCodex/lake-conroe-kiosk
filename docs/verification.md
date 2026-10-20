# Verification record

Development verification on October 20, 2026. These results describe this cloud
instance and isolated test fixtures; they do not certify Raspberry Pi hardware
or successful access to blocked upstream services.

## Passed

- Python 3.12 virtual environment installed from `requirements.txt`; repeat
  installation completed successfully without modifying configuration.
- All **16 pinned runtime dependencies** resolved and downloaded as **binary
  wheels for ARMv7 CPython 3.11 and 3.13**, corresponding to Raspberry Pi OS
  Bookworm and Trixie 32-bit. The installer enforces Python 3.11+ and wheel-only
  installation; no Rust compilation is needed. TLS and package verification
  remained enabled. This validates dependency availability, not Pi hardware.
- **58 Python tests** passed with `python -m unittest discover -s tests -v`.
  They exercise weather/alert parsing, model timestamps and daylight saving,
  unit conversions, SJRA/USGS parsing and datums, missing/no-data values,
  camera discovery, persistent cache recovery, partial failures, stale alerts,
  configuration validation, retry limits/Retry-After, and HTTP/static routes.
  Network-dependent provider tests use explicit synthetic fixtures or HTTP
  mocks; fixture results are never returned by production endpoints.
- The actual server started, served the HTML/JS, and returned HTTP 200 from
  `/api/dashboard`, source endpoints, and `/api/health`. It was stopped and
  restarted successfully; cached camera configuration was restored. The health
  response correctly reports **degraded**, with unavailable weather/forecast/
  lake/alert sources and usable but unverified camera configuration metadata.
- Chromium checks at **1920 × 1080** and **1280 × 720** passed: no document
  scrolling, panel overflow, or metric overlap; six hourly slots, three daily
  slots, current clock updates, severity colors, Celsius conversion, an unknown
  alert state after stale empty alerts, calendar-date matching across midnight,
  and configurable panel visibility. Populated-panel checks are isolated test
  fixtures, not claims of live measurements.
- **25 camera browser checks** passed using an explicitly mocked supported
  player/image source: muted playback calls, no LIVE before PLAYING, removal
  during errors/buffering, retry, recovery, alternative selection, stalled-media
  detection, image-refresh timeout, cleanup, and exact 16:9 player fitting at
  both resolutions. This does not verify the actual YouTube feed.
- Pi shell scripts passed `bash -n`; the installer passed its complete
  `--dry-run` option combination. Rendered systemd templates passed syntax
  verification. No actual Pi package installation, service enabling, desktop
  autostart edit, or sports-scoreboard modification was performed.

Starlette emits a deprecation warning for the HTTPX-backed TestClient with the
installed transitive dependency version; all API tests still pass. Production
HTTP fetching uses HTTPX directly and does not use TestClient.

## Actual screenshots

- [1920 × 1080](dashboard-1920x1080.png)
- [1280 × 720](dashboard-1280x720.png)

Both screenshots were inspected. They show the real current-instance result:
unavailable live sources, no invented measurements, and unknown alert status.
The screenshots do not use fixture responses or substitute scenery for a camera.
The browser test regenerates them from the actual running server.

## Blocked or not verified

| Check | Observed result / remaining action |
| --- | --- |
| Open-Meteo current/daily and NWS alerts | Cloud egress proxy returned `403 Forbidden` before a provider response. Apply the saved outbound-domain requirements in environment settings and retry, or verify on the Pi's network. |
| SJRA published HTML | Same proxy denial. Conservative parsing is unit tested, but the current live HTML shapes are unverified. Chart-only pages without labeled measurements remain unavailable. |
| USGS station 08067600 | Proxy denied the public NWIS endpoint. Current station parameters and live observations remain unverified. |
| Camera source / YouTube | Official page and YouTube oEmbed denied by the proxy. The current ID, provider embedding permission, and actual playback remain unverified. An actual PLAYING event is required before the UI shows LIVE. |
| OneRain structured feed | Dashboard access was denied. No public structured feed has been confirmed; no protected/guessed endpoint is used. |
| Measured 24-hour rainfall | Unavailable until a compatible observed interval feed is confirmed. Forecast precipitation is not substituted. |
| Pi boot / HDMI / screen wake / acceleration | Must be tested on a physical Pi after following `raspberry-pi.md`; cloud Chromium cannot prove these behaviors. |
| Reference-image matching | Only the text brief was received. The design follows its specified colors, proportions, panel order, and camera emphasis. |

Reusable cloud `install_script`, `start_skill`, and exact outbound-domain
requirements were saved to the environment draft. Saving does not apply network
changes, publish a snapshot, or prove restoration in a new task. Review and save
the settings, then publish the environment through the product when appropriate.
