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
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
RUN_SLOTS = threading.BoundedSemaphore(2)  # each run calls the model several times; cap concurrent runs


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
            if not self._same_origin():
                return self._json({"error": "cross-origin requests are not allowed"}, 403)
            q = (parse_qs(u.query).get("q") or [""])[0].strip()[:1500]
            if not q:
                return self._json({"error": "empty question"}, 400)
            if not RUN_SLOTS.acquire(blocking=False):
                return self._json({"error": "busy, try again in a moment"}, 429)
            try:
                return self._stream(q)
            finally:
                RUN_SLOTS.release()
        return super().do_GET()

    def _same_origin(self) -> bool:
        """Block other websites (and DNS rebinding) from starting model runs through the browser."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:
            return False
        # Fail closed: a browser request must prove it came from this page.
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None:
            return site == "same-origin"
        src = urlparse(self.headers.get("Origin") or self.headers.get("Referer") or "")
        return f"{src.scheme}://{src.netloc}" == f"http://{self.headers.get('Host')}"

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
