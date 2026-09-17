from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess
import tempfile
import httpx

from .paths import DATA_ROOT

CACHE_ROOT = DATA_ROOT / "data" / "map_cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

MIN_CACHE_HOURS = 168
OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "ITICAS/0.26.3 (Nigeria Traffic Intelligence and Congestion Analysis System)"

class MapTileUnavailable(RuntimeError):
    pass

def _cache_path(z: int, x: int, y: int) -> Path:
    return CACHE_ROOT / str(z) / str(x) / f"{y}.png"

def _fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age <= MIN_CACHE_HOURS * 3600

def _is_image(raw: bytes) -> bool:
    return (
        raw.startswith(b"\x89PNG\r\n\x1a\n")
        or raw.startswith(b"\xff\xd8\xff")
        or raw.startswith(b"RIFF")
    )

def _download_httpx_ipv4(url: str, timeout: float = 12.0):
    transport = httpx.HTTPTransport(local_address="0.0.0.0", retries=0)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/png,image/*;q=0.9,*/*;q=0.1",
        "Referer": "http://127.0.0.1:8765/map",
    }
    with httpx.Client(
        transport=transport,
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        r = client.get(url)
        r.raise_for_status()
        raw = r.content
        if not _is_image(raw):
            raise MapTileUnavailable("Provider response was not a PNG/JPEG/WebP tile")
        return raw, r.headers.get("content-type", "image/png").split(";")[0]

def _download_curl_ipv4(url: str, timeout: int = 15):
    fd, temp_name = tempfile.mkstemp(suffix=".tile")
    os.close(fd)
    try:
        cmd = [
            "curl.exe", "-4", "-L", "--fail", "--silent", "--show-error",
            "--connect-timeout", "8", "--max-time", str(timeout),
            "-A", USER_AGENT,
            "-H", "Accept: image/png,image/*;q=0.9,*/*;q=0.1",
            "-e", "http://127.0.0.1:8765/map",
            "-o", temp_name,
            url,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if p.returncode != 0:
            raise MapTileUnavailable((p.stderr or f"curl exit {p.returncode}").strip())
        raw = Path(temp_name).read_bytes()
        if not _is_image(raw):
            raise MapTileUnavailable("curl response was not a real image tile")
        return raw, "image/png"
    finally:
        try:
            os.remove(temp_name)
        except OSError:
            pass

def _download(url: str):
    errors = []
    try:
        return _download_httpx_ipv4(url)
    except Exception as exc:
        errors.append(f"httpx IPv4: {exc}")
    try:
        return _download_curl_ipv4(url)
    except Exception as exc:
        errors.append(f"curl IPv4: {exc}")
    raise MapTileUnavailable(" | ".join(errors))

def tile(z: int, x: int, y: int):
    if z < 0 or z > 22 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        raise MapTileUnavailable("Invalid tile coordinate")

    path = _cache_path(z, x, y)
    if _fresh(path):
        return path.read_bytes(), "image/png", "ITICAS tile cache"

    errors = []

    custom = os.environ.get("ITICAS_BASEMAP_TILE_URL", "").strip()
    if custom:
        try:
            raw, ctype = _download(custom.format(z=z, x=x, y=y))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return raw, ctype, "Configured basemap provider"
        except Exception as exc:
            errors.append(f"configured basemap: {exc}")

    try:
        raw, ctype = _download(OSM_TILE.format(z=z, x=x, y=y))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return raw, ctype, "OpenStreetMap via ITICAS IPv4"
    except Exception as exc:
        errors.append(f"OpenStreetMap: {exc}")

    if path.exists():
        return path.read_bytes(), "image/png", "ITICAS stale tile cache"

    raise MapTileUnavailable(" | ".join(errors) or "No basemap provider available")
