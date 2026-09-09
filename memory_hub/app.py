"""One cross-platform owner for the browser dashboard and optional system tray."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import urllib.error
import urllib.request
import webbrowser

from .app_config import bootstrap_environment
from .dashboard import create_server, default_dashboard_port
from .dashboard_data import revision
from .manager import MemoryManager


def running_instance(vault, port):
    """Probe only the requested port; never stop an unrelated application."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/instance', timeout=2) as response:
            value = json.loads(response.read(4096))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return (isinstance(value, dict) and value.get('app') == 'ai-memory-hub'
            and value.get('vault') == revision(str(Path(vault).resolve())))


def run(vault, port=None, tray=True, open_browser=True):
    bootstrap_environment(vault)  # config.json fills gaps; an explicit env var still wins.
    port = port if port is not None else default_dashboard_port()
    url = f'http://127.0.0.1:{port}/'
    if port and running_instance(vault, port):
        if open_browser:
            webbrowser.open(url)
        return
    manager = MemoryManager(vault)
    server = None
    thread = None
    try:
        server = create_server(manager, port=port)
        manager.reindex()
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        print(f'AI Memory Hub: {url}', flush=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        if open_browser:
            webbrowser.open(url)
        if tray:
            try:
                import pystray
                from .tray import icon_image
                icon = pystray.Icon('ai-memory-hub', icon_image(), 'AI Memory Hub',
                    pystray.Menu(
                        pystray.MenuItem('Open memory workspace', lambda: webbrowser.open(url), default=True),
                        pystray.MenuItem('Quit AI Memory Hub', lambda icon, item: icon.stop()),
                    ))
                try:
                    icon.run()
                finally:
                    icon.stop()
                return
            except Exception as exc:
                print(f'Tray unavailable ({exc}). Browser dashboard remains running.', flush=True)
        print('Press Ctrl+C in this terminal to stop AI Memory Hub.', flush=True)
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            if thread and thread.is_alive():
                server.shutdown()
                thread.join()
            server.server_close()
        manager.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', default=os.environ.get('AI_MEMORY_VAULT'))
    # No default here on purpose: the dashboard port may come from the vault's
    # config.json, which isn't known until run() bootstraps it from --vault.
    # Resolving default_dashboard_port() this early would only see an env var,
    # never a config-file setting.
    parser.add_argument('--port', type=int, default=None)
    parser.add_argument('--no-tray', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not args.vault:
        parser.error('Set --vault or AI_MEMORY_VAULT')
    try:
        run(args.vault, args.port, not args.no_tray, not args.no_browser)
    except OSError as exc:
        parser.exit(1, f'Cannot start AI Memory Hub: {exc}. The port may belong to another app or vault.\n')


if __name__ == '__main__':
    main()

