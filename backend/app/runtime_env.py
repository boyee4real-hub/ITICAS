from __future__ import annotations

import os
from pathlib import Path

def load_runtime_env(env_path: Path) -> None:
    """Dependency-free .env loader used before Pydantic settings initialise.

    Existing process environment variables win. This is intentionally simple
    and supports the KEY=value form used by ITICAS deployment configuration.
    """
    try:
        if not env_path.exists():
            return
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except Exception:
        # Settings still retain their declared defaults if the deployment file
        # is unreadable. Diagnostics will expose missing provider configuration.
        return
