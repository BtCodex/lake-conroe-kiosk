"""Serve a phone layout with the original dashboard's data API and widgets."""

import os
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import ROOT, load_config
from app.main import create_app

MOBILE = Path(__file__).resolve().parent


def mobile_document() -> str:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    html = html.replace("<title>Lake Conroe Live</title>", "<title>Lake Dashboard</title>", 1)
    html = html.replace('src="/static/app.js"', 'src="/mobile/dashboard.js?v=6"', 1)
    html = html.replace("</head>", """  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="stylesheet" href="/mobile/mobile.css?v=6">
  <script type="module" src="/mobile/mobile.js?v=5"></script>
</head>""", 1)

    install_panel = """    <div class="install-app" id="install-app" hidden>
      <button class="mobile-button" id="install-button" type="button" aria-controls="install-help" aria-expanded="false">Install app</button>
      <p id="install-help" hidden>In Chrome, tap ⋮, then Add to Home screen or Install and create shortcut. Choose Install when Chrome offers it.</p>
    </div>

"""
    html = html.replace('    <main class="main-grid">', install_panel + '    <main class="main-grid">', 1)

    # Place the existing alert strip after the footer readings.
    alert_start = html.index('      <div class="alert-bar"')
    alert_end = html.index('      <div class="footer-meta"', alert_start)
    alert = html[alert_start:alert_end]
    html = html[:alert_start] + html[alert_end:]
    html = html.replace('    </footer>', alert + '    </footer>', 1)

    camera_bottom = '<div class="camera-bottom">'
    camera_actions = ('''<div class="camera-actions">
          <button class="mobile-button" id="camera-go-live" type="button" aria-controls="camera-stage" hidden>Go live</button>
          <button class="mobile-button" id="camera-fullscreen" type="button" aria-controls="camera-stage" hidden>Full screen</button>
        </div>''')
    html = html.replace(camera_bottom, camera_bottom + camera_actions, 1)

    rainfall_link = ('<a class="rainfall-link" target="_blank" rel="noopener" '
                     'href="https://sanjacinto.onerain.com/dashboard/?'
                     'dashboard=c03aab24-7518-419b-9dfa-b151879a06c8&amp;refresh=60&amp;scroll=4772">'
                     'San Jacinto OneRain</a>')
    return html.replace('<div class="source-line" id="lake-source">',
                        rainfall_link + '\n          <div class="source-line" id="lake-source">', 1)


def create_mobile_app(*, providers=None, cache_dir=None):
    settings = load_config(os.environ.get("LAKE_DASHBOARD_CONFIG") or ROOT / "config/settings.example.json")
    directory = Path(cache_dir or os.environ.get("LAKE_DASHBOARD_CACHE_DIR")
                     or Path.home() / ".cache/lake-dashboard-mobile").resolve()
    application = create_app(settings, providers=providers, cache_dir=directory)
    application.title = "Lake Dashboard"
    document = mobile_document()
    dashboard_script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    dashboard_script = dashboard_script.replace("from './camera.js'", "from '/mobile/live-camera.js?v=6'", 1)
    dashboard_script = dashboard_script.replace("from './icons.js'", "from '/static/icons.js'", 1)

    # Replace the index on this app instance while keeping the original API and static routes.
    routes = application.router.routes
    routes.remove(next(route for route in routes if route.path == "/"))

    @application.get("/", include_in_schema=False)
    async def index():
        return HTMLResponse(document, headers={"Cache-Control": "no-cache"})

    @application.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(MOBILE / "assets/manifest.webmanifest", media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})

    @application.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(MOBILE / "assets/sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @application.get("/mobile/dashboard.js", include_in_schema=False)
    async def mobile_dashboard_script():
        return Response(dashboard_script, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    application.mount("/mobile", StaticFiles(directory=MOBILE / "assets"), name="mobile")
    return application


app = create_mobile_app()
