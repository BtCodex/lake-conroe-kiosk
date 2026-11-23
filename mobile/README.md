# Lake Dashboard

The Moto G 5G (2024) app reuses the Lake Conroe kiosk's widget markup, styles,
scripts, Python providers, and polling. The portrait layout gives the camera the
full screen width and keeps readings large in scrollable cards. Landscape puts
the camera alongside the readings. The app runs on its own origin and has its
own data cache.

## Local run

From the repository root, install the pinned `requirements.txt` in a Python
3.11+ environment, then run:

```sh
python -m uvicorn mobile.main:app --host 127.0.0.1 --port 8081
```

Open `http://127.0.0.1:8081` on the same computer. The mobile service reads the
tracked default configuration. To customize it, use `LAKE_DASHBOARD_CONFIG` to
point to a separate settings file and `LAKE_DASHBOARD_CACHE_DIR` to select a
writable cache directory. The default local cache is
`~/.cache/lake-dashboard-mobile`.

## Independent HTTPS deployment

Create a Docker web service on a host that provides HTTPS. Use the repository
root as the build context and `mobile/Dockerfile` as the Dockerfile. The service
binds to `PORT` when the host supplies it and otherwise listens on `8081`.
`/api/health` is the health check. On a host with persistent storage, mount a
writable volume at `/var/cache/lake-dashboard` to retain last-good readings
across restarts. Use one replica to keep upstream polling centralized.

For a no-cost Render deployment, select **New → Web Service**, connect this
repository, select the `mobile-dashboard` branch, then select the **Docker**
runtime and **Free** instance type. Leave the root directory unset, set the
Dockerfile Path to `mobile/Dockerfile`, and set the Health Check Path to
`/api/health`. Render provides an HTTPS URL after the service goes live. Free
instances can sleep when idle and lose their local cache when restarted. The
dashboard starts polling as soon as the service wakes up.

The browser checks for a fresh snapshot every 15 seconds. Weather and hourly
conditions refresh every 5 minutes, daily forecasts and camera discovery every
30 minutes, lake readings every 3 minutes, and NWS alerts every 2 minutes, as in
the original defaults. The installed shell can open offline. Weather, lake data,
alerts, and camera playback use the network. The existing 24-hour rainfall card
shows `--` because the existing provider has no verified measured interval
feed. Its OneRain link goes to the official San Jacinto dashboard, which may
ask you to sign in.

## Install on the Moto G 5G (2024)

1. Open the deployment's HTTPS URL in Chrome.
2. Tap **⋮ → Add to Home screen → Install**. Some Chrome versions show
   **Install app** directly in the menu.
3. Confirm **Lake Dashboard** and tap its lake-wave icon from the home screen.
   The installed app opens without Chrome's address bar.

Tap **Full screen** below the camera to enlarge the video. Chrome on Android
can rotate the camera to landscape in full-screen mode. Tap **Exit full screen**
or use Android's Back button to return to the dashboard.
