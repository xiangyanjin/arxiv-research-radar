"""Loopback-only dashboard and same-origin mutation endpoints."""
from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse

from .service import Radar, BusyError


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves a reverse-DNS name during startup. The dashboard
        # binds only to loopback and has no use for that potentially slow lookup.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def serve(port=8765, root=None, *, radar=None):
    radar = radar if radar is not None else Radar(root) if root else Radar()

    class Handler(BaseHTTPRequestHandler):
        def local_request(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in allowed and (not origin or origin in {"http://" + x for x in allowed})

        def send(self, body, content_type="application/json; charset=utf-8", status=200, attachment=None):
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body, ensure_ascii=False)
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # Reads contain private notes too. Check Host on both reads and
            # writes to reject DNS rebinding through an attacker-owned domain.
            if not self.local_request():
                return self.send({"error": "仅允许本机页面访问"}, status=403)
            request = urlparse(self.path)
            params = parse_qs(request.query)
            view = {key: params.get(key, [default])[0] for key, default in
                    (("topic", ""), ("filter", "all"), ("q", ""), ("sort", "relevance"))}
            try:
                if request.path == "/api/state":
                    return self.send(radar.state())
                if request.path == "/api/papers":
                    papers = radar.papers(**view)
                    return self.send({"papers": papers, "total": len(papers)})
                if request.path == "/api/runs":
                    return self.send({"runs": radar.store.runs()})
                if request.path == "/api/digest":
                    return self.send(radar.digest())
                if request.path == "/api/exports/bib":
                    return self.send(radar.bibtex(scope=params.get("scope", [""])[0], **view),
                                     "application/x-bibtex; charset=utf-8", attachment="research-library.bib")
                if request.path == "/api/exports/markdown":
                    return self.send(radar.markdown(scope=params.get("scope", ["view"])[0], **view),
                                     "text/markdown; charset=utf-8", attachment="research-library.md")
                relative = request.path.lstrip("/") or "index.html"
                path = (radar.root / "static" / relative).resolve()
                if not path.is_relative_to((radar.root / "static").resolve()) or not path.is_file():
                    return self.send({"error": "未找到"}, status=404)
                return self.send(path.read_bytes(), (mimetypes.guess_type(path)[0] or "application/octet-stream") + "; charset=utf-8")
            except ValueError as error:
                return self.send({"error": str(error)}, status=400)
            except Exception as error:
                return self.send({"error": str(error)}, status=500)

        def do_POST(self):
            if not self.local_request():
                return self.send({"error": "仅允许本机页面发起操作"}, status=403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                # 5,000 Unicode characters can use up to 60 KB when JSON
                # escapes supplementary characters; bound bytes separately.
                if not 0 <= size <= 65536:
                    return self.send({"error": "请求过大"}, status=413)
                body = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/scan":
                    handle = radar.acquire()
                    threading.Thread(target=radar.scan, kwargs={"handle": handle}, daemon=True).start()
                    return self.send({"started": True}, status=202)
                if self.path == "/api/feedback":
                    radar.store.feedback(body.get("id"), body.get("feedback"))
                    return self.send({"ok": True})
                if self.path == "/api/library":
                    return self.send({"ok": True, "paper": radar.store.update_library(body)})
                return self.send({"error": "未知操作"}, status=404)
            except BusyError as error:
                return self.send({"error": str(error)}, status=409)
            except (ValueError, AttributeError) as error:
                return self.send({"error": str(error)}, status=400)
            except Exception as error:
                return self.send({"error": str(error)}, status=500)

        def log_message(self, format, *args):
            if args and str(args[1] if len(args) > 1 else "") not in ("200", "304"):
                super().log_message(format, *args)

    server = LoopbackHTTPServer(("127.0.0.1", port), Handler)
    print(f"arXiv 研究雷达：http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
