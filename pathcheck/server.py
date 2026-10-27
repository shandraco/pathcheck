"""Small web server (standard library only): the page, a status endpoint and a live run stream.

GET /                 the student page
GET /api/status       data layer + Meterless Nightshift status
GET /api/run?q=...    Server-Sent Events: every agent step, then the final answer
"""
import json
import queue
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config
from .agents import Team
from .data import open_data
from .llm import MeterlessClient

WEB = config.ROOT / "web"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/status":
            st = MeterlessClient().status()
            try:
                d = open_data()
                data_ok, engine = d.ping(), d.engine
            except Exception as e:  # noqa: BLE001 - report any data-layer failure to the page
                data_ok, engine = False, f"error: {e}"
            return self._json({"llm": st["state"], "models": st["models"][:20], "data": engine, "data_ok": data_ok,
                               "sample_mode": config.SAMPLE_MODE})
        if u.path == "/api/run":
            q = (parse_qs(u.query).get("q") or [""])[0].strip()[:1500]
            if not q:
                return self._json({"error": "empty question"}, 400)
            return self._stream(q)
        return super().do_GET()

    def _stream(self, q):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        events: queue.Queue = queue.Queue()

        def work():
            try:
                Team(emit=events.put).run(q)
            except Exception as e:  # noqa: BLE001 - surface the failure to the student page
                events.put({"agent": "system", "action": "error", "detail": str(e)})
            events.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            ev = events.get()
            if ev is None:
                break
            try:
                self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break


def main():
    port = int(config.env("PORT", "8931"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PathCheck on http://127.0.0.1:{port}  (sample mode: {config.SAMPLE_MODE})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
