"""Serve the site locally with live reload. Standard library only.

    python -m pipeline.serve              # http://127.0.0.1:8000, or the next free port
    python -m pipeline.serve --open       # and open it in the browser
    python -m pipeline.serve --lan        # also reachable from a phone on the same Wi-Fi

When a port is taken, the next free one is used, so there is no "address
already in use" error. The page reloads by itself when a file under site/
changes, including the data the pipeline writes, and nothing is cached, so
the browser always shows the current files. The site needs data: if
site/data/latest.json is missing, build it first with

    python -m pipeline.run --region sxm --sample   # synthetic, offline
    python -m pipeline.run --region sxm            # live data
"""
from __future__ import annotations

import argparse
import errno
import functools
import http.server
import os
import pathlib
import socket
import sys
import threading
import time
import webbrowser

from .run import ROOT

RELOAD = "/__reload"
SNIPPET = (b"<script>/* live reload, added by pipeline.serve */"
           b"new EventSource('" + RELOAD.encode() + b"').onmessage=function(){location.reload()}</script>")


class Watcher:
    """Notices when any file under `root` changes: `stamp` moves on."""

    def __init__(self, root: pathlib.Path, interval: float = 0.5):
        self.root, self.interval = root, interval
        self.stamp = self.scan()
        threading.Thread(target=self._run, daemon=True).start()

    def scan(self) -> tuple:
        newest, count = 0.0, 0
        for folder, _, files in os.walk(self.root):
            for name in files:
                try:
                    newest = max(newest, os.stat(os.path.join(folder, name)).st_mtime)
                    count += 1
                except OSError:  # removed while scanning
                    pass
        return newest, count  # the count catches deleted files

    def _run(self):
        while True:
            time.sleep(self.interval)
            self.stamp = self.scan()


class Handler(http.server.SimpleHTTPRequestHandler):
    watcher: Watcher = None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == RELOAD:
            return self.stream_reloads()
        if path.endswith("/") or path.endswith(".html"):
            return self.send_html(path)
        return super().do_GET()

    def send_html(self, path: str):
        file = pathlib.Path(self.translate_path(path))
        if file.is_dir():
            file = file / "index.html"
        if not file.is_file():
            return self.send_error(404)
        body = file.read_bytes()
        body = body.replace(b"</body>", SNIPPET + b"</body>", 1) if b"</body>" in body else body + SNIPPET
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream_reloads(self):
        """Server-sent events: one "reload" message when a file changes, keep-alive comments meanwhile."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        start, last = self.watcher.stamp, time.monotonic()
        try:
            while True:
                time.sleep(self.watcher.interval)
                if self.watcher.stamp != start:
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                    return
                if time.monotonic() - last > 15:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    last = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page was closed or reloaded

    def log_message(self, fmt, *args):
        if RELOAD not in self.path:
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = False  # so a port another program holds counts as taken
    daemon_threads = True


def bind(host: str, port: int, handler, tries: int = 20) -> Server:
    """A server on `port`, or the first free port after it, or any free port."""
    for candidate in range(port, port + tries):
        try:
            return Server((host, candidate), handler)
        except OSError as e:
            if e.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
    return Server((host, 0), handler)


def lan_address() -> str | None:
    """This computer's address on the local network, for a phone on the same Wi-Fi."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000, help="first port to try (default 8000)")
    p.add_argument("--lan", action="store_true", help="listen on all interfaces, for a phone on the same network")
    p.add_argument("--open", action="store_true", help="open the site in the default browser")
    p.add_argument("--dir", default=str(ROOT / "site"), help="folder to serve (default site/)")
    args = p.parse_args(argv)
    root = pathlib.Path(args.dir).resolve()
    handler = functools.partial(Handler, directory=str(root))
    Handler.watcher = Watcher(root)
    server = bind("0.0.0.0" if args.lan else "127.0.0.1", args.port, handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    note = "" if port == args.port else f" (port {args.port} was taken)"
    print(f"OpenSargasso at {url}{note}, serving {root}", flush=True)
    if args.lan and lan_address():
        print(f"On a phone on the same Wi-Fi: http://{lan_address()}:{port}/", flush=True)
    if not (root / "data" / "latest.json").exists():
        print("No site/data/latest.json yet. In another terminal, run one of:\n"
              "  python -m pipeline.run --region sxm --sample   # synthetic, offline\n"
              "  python -m pipeline.run --region sxm            # live data\n"
              "The page reloads when it appears.", flush=True)
    print("Live reload is on. Press Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
