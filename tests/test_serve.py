"""Local server: steps around a taken port, adds live reload to pages, never caches, reloads on change."""
import functools
import http.client
import socket
import threading

from pipeline import serve


def start(tmp_path, port=0):
    serve.Handler.watcher = serve.Watcher(tmp_path, interval=0.05)
    server = serve.bind("127.0.0.1", port, functools.partial(serve.Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_taken_port_is_skipped(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        server = serve.bind("127.0.0.1", port, serve.Handler)
        try:
            assert server.server_address[1] != port
        finally:
            server.server_close()


def test_pages_get_live_reload_and_nothing_is_cached(tmp_path):
    (tmp_path / "index.html").write_text("<html><body><p>hi</p></body></html>")
    (tmp_path / "app.js").write_text("var x = 1;")
    server = start(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("GET", "/")
        page = conn.getresponse()
        body = page.read()
        assert page.status == 200 and page.getheader("Cache-Control") == "no-store"
        assert body.endswith(serve.SNIPPET + b"</body></html>")
        conn.request("GET", "/app.js")
        script = conn.getresponse()
        assert script.read() == b"var x = 1;" and script.getheader("Cache-Control") == "no-store"
    finally:
        server.shutdown()
        server.server_close()


def test_a_changed_file_sends_reload(tmp_path):
    (tmp_path / "index.html").write_text("<html><body></body></html>")
    server = start(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.request("GET", serve.RELOAD)
        events = conn.getresponse()
        assert events.getheader("Content-Type") == "text/event-stream"
        (tmp_path / "data.json").write_text("{}")          # the pipeline writes new data
        assert events.readline() == b"data: reload\n"
    finally:
        server.shutdown()
        server.server_close()
