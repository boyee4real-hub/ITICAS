from pathlib import Path
import os
import sys

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ASSET_ROOT = Path(sys._MEIPASS)
    default_data_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ITICAS"
    DATA_ROOT = Path(os.environ.get("ITICAS_DATA_ROOT", str(default_data_root))).expanduser().resolve()
else:
    ASSET_ROOT = Path(__file__).resolve().parents[2]
    DATA_ROOT = Path(os.environ.get("ITICAS_DATA_ROOT", str(ASSET_ROOT))).expanduser().resolve()

DATA_ROOT.mkdir(parents=True, exist_ok=True)
