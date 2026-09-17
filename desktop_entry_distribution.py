from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

_devnull = open(os.devnull, "w", encoding="utf-8", buffering=1)
if sys.stdout is None:
    sys.stdout = _devnull
if sys.stderr is None:
    sys.stderr = _devnull

APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ITICAS"
APPDATA.mkdir(parents=True, exist_ok=True)
os.environ["ITICAS_DATA_ROOT"] = str(APPDATA)

# These imports intentionally happen only after ITICAS_DATA_ROOT is fixed.
from backend.app.paths import DATA_ROOT
from backend.app.runtime_env import load_runtime_env
load_runtime_env(DATA_ROOT / ".env")

from backend.app.runtime_bootstrap import bootstrap_runtime_database
bootstrap_runtime_database()

import uvicorn
from backend.app.main import app
from backend.app.config import settings

def is_running(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0

browser_host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
url = f"http://{browser_host}:{settings.port}/login"

if is_running(settings.host, settings.port):
    webbrowser.open(url)
    raise SystemExit(0)

def open_ui() -> None:
    for _ in range(120):
        time.sleep(0.25)
        if is_running(settings.host, settings.port):
            webbrowser.open(url)
            return

threading.Thread(target=open_ui, daemon=True).start()

uvicorn.run(
    app,
    host=settings.host,
    port=settings.port,
    log_level="warning",
    access_log=False,
    log_config=None,
)
