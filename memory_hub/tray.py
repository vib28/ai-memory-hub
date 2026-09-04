from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from PIL import Image, ImageDraw
import pystray

from .dashboard import DashboardHandler
from .manager import MemoryManager

def icon_image():
    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), outline="black", width=4)
    d.line((32, 12, 32, 52), fill="black", width=3)
    d.arc((15, 16, 34, 38), 70, 290, fill="black", width=3)
    d.arc((30, 16, 49, 38), 250, 110, fill="black", width=3)
    d.arc((15, 28, 34, 50), 70, 290, fill="black", width=3)
    d.arc((30, 28, 49, 50), 250, 110, fill="black", width=3)
    return img

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=os.environ.get("AI_MEMORY_VAULT"))
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    if not args.vault:
        p.error("Set --vault or AI_MEMORY_VAULT")

    manager = MemoryManager(args.vault)
    manager.reindex()
    DashboardHandler.manager = manager
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def open_dashboard(icon=None, item=None):
        webbrowser.open(url)

    def quit_app(icon, item):
        server.shutdown()
        manager.close()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Memory Dashboard", open_dashboard, default=True),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("ai-memory-hub", icon_image(), "AI Memory Hub", menu)
    webbrowser.open(url)
    icon.run()

if __name__ == "__main__":
    main()
