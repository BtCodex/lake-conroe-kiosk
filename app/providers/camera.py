"""Official embed discovery/configuration; discovery never proves playback is live."""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit

from app.network import get_text

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}


def safe_url(value: str | None) -> str | None:
    """Accept explicit HTTP(S) sources, without embedded credentials."""
    if not value:
        return None
    value = unescape(str(value).strip())
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Camera URLs must be HTTP(S) URLs without embedded credentials")
    return value


def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(safe_url(url))
    host = (parsed.hostname or "").lower()
    parts = parsed.path.strip("/").split("/")
    candidate = None
    if host in YOUTUBE_HOSTS:
        if len(parts) == 2 and parts[0] in {"embed", "live"}:
            candidate = parts[1]
        elif parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
    elif host == "youtu.be" and len(parts) == 1:
        candidate = parts[0]
    return candidate if candidate and VIDEO_ID.fullmatch(candidate) else None


class _EmbedParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "iframe":
            return
        attributes = dict(attrs)
        for key in ("src", "data-src", "data-lazy-src"):
            value = attributes.get(key)
            if value:
                self.urls.append("https:" + value if value.startswith("//") else value)


def discover_youtube_id(page: str) -> str | None:
    parser = _EmbedParser()
    parser.feed(page)
    # Accept supported embed URLs, including those within lazy-load markup.
    for candidate in parser.urls:
        try:
            result = youtube_id(candidate)
        except ValueError:
            continue
        if result:
            return result
    return None


def infer_provider(url: str) -> str:
    if youtube_id(url):
        return "youtube"
    if urlsplit(url).path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    return "iframe"


async def fetch_camera(config: dict, client) -> dict:
    camera = config.get("camera", {})
    provider = camera.get("provider", "youtube")
    if provider not in {"youtube", "image", "iframe", "disabled"}:
        raise ValueError("Unsupported camera provider")
    result = {
        "source": "Camera configuration",
        "provider": provider,
        "url": safe_url(camera.get("url")) if provider != "disabled" else None,
        "video_id": None,
        "attribution": camera.get("attribution", "ABC13 / LakeConroe.com"),
        "source_url": safe_url(camera.get("source_page")),
        "status": "configured",
        "playback_verified": False,
        "limitations": [],
        "retry_seconds": max(10, int(camera.get("retry_seconds", 30))),
        "image_refresh_seconds": max(15, int(camera.get("image_refresh_seconds", 60))),
        "alternative_url": safe_url(camera.get("alternative_url")),
    }
    alternative = result["alternative_url"]
    result["alternative_provider"] = infer_provider(alternative) if alternative else None
    if provider == "disabled":
        return result
    if provider == "youtube":
        result["video_id"] = youtube_id(result["url"])
        if camera.get("discover_from_source", True) and result["source_url"]:
            try:
                page = await get_text(client, result["source_url"])
                discovered = discover_youtube_id(page)
                if discovered:
                    result["video_id"] = discovered
                    result["url"] = f"https://www.youtube.com/embed/{discovered}"
                    result["source"] = "LakeConroe.com official camera page"
                    result["status"] = "discovered"
                    result["discovered_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    result["limitations"].append("No supported YouTube embed was found on the official page; using the configured source.")
            except Exception as exc:
                # Do not expose proxy URLs, query credentials, or response bodies.
                result["limitations"].append(f"Official camera discovery is unavailable ({type(exc).__name__}); the configured source has not been verified.")
        if not result["video_id"]:
            raise ValueError("A valid supported YouTube video URL is required")
        result["limitations"].append("An embedded-player PLAYING event is required before the display shows LIVE; source discovery alone does not verify playback.")
    elif not result["url"]:
        raise ValueError("A camera URL is required")
    return result
