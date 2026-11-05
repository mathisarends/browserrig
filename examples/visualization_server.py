"""Local deterministic documents and a paced download for the visual example."""

import html
import http.server
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


@contextmanager
def visualization_site(directory: Path, theme: str):
    page = Path(__file__).with_name("visualization.html").read_text(encoding="utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            path = urlsplit(self.path).path
            if path == "/download":
                self.download()
                return
            if path.startswith("/proof/"):
                name = Path(path).name
                target = directory / name
                if target.is_file() and target.suffix == ".png":
                    self.respond(target.read_bytes(), "image/png")
                    return
            if path == "/gallery" and (directory / "gallery.html").is_file():
                self.respond((directory / "gallery.html").read_bytes(), "text/html")
                return
            title = "Research notes" if path == "/" else "Saved notes"
            document = page.replace("{{theme}}", html.escape(theme)).replace(
                "{{title}}", title
            )
            self.respond(document.encode(), "text/html; charset=utf-8")

        def respond(self, body: bytes, mime: str):
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def download(self):
            body = b"Browserrig\nNative input, observable outcomes.\n" * 2000
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header(
                "Content-Disposition", 'attachment; filename="browser-notes.txt"'
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            for offset in range(0, len(body), 4096):
                self.wfile.write(body[offset : offset + 4096])
                self.wfile.flush()
                time.sleep(0.08)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
