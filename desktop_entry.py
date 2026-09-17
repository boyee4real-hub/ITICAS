import socket, threading, time, webbrowser
import uvicorn
from backend.app.main import app
from backend.app.config import settings

def port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0

host=settings.host; port=settings.port
if not port_free(host,port):
    webbrowser.open(f"http://{host}:{port}")
    raise SystemExit(0)

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://{host}:{port}")

threading.Thread(target=open_browser,daemon=True).start()
uvicorn.run(app,host=host,port=port,log_level="info")
