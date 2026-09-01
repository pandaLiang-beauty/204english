#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import mimetypes
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
FORWARDED_HEADERS = {"x-forwarded-for", "x-forwarded-proto", "x-real-ip"}


def build_proxy_headers(incoming_headers, peer: str) -> dict[str, str]:
    headers = {}
    for key, value in incoming_headers.items():
        lowered = key.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered in FORWARDED_HEADERS or lowered == "host":
            continue
        headers[key] = value
    headers["Host"] = incoming_headers.get("Host", "")
    headers["X-Real-IP"] = peer
    headers["X-Forwarded-For"] = peer
    headers["X-Forwarded-Proto"] = "http"
    return headers


class FrontendProxyHandler(BaseHTTPRequestHandler):
    static_root: Path
    backend_host: str
    backend_port: int
    backend_scheme: str
    base_path: str

    server_version = "ProStudyLocalFrontend/1.0"

    def do_GET(self) -> None:
        self.dispatch()

    def do_HEAD(self) -> None:
        self.dispatch(head_only=True)

    def do_POST(self) -> None:
        self.dispatch()

    def do_PUT(self) -> None:
        self.dispatch()

    def do_PATCH(self) -> None:
        self.dispatch()

    def do_DELETE(self) -> None:
        self.dispatch()

    def do_OPTIONS(self) -> None:
        self.dispatch()

    def dispatch(self, *, head_only: bool = False) -> None:
        parsed = urlparse(self.path)
        path = self.strip_base_path(parsed.path)
        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if not head_only:
                self.wfile.write(b"ok\n")
            return
        if path.startswith("/api/"):
            backend_path = path + (f"?{parsed.query}" if parsed.query else "")
            self.proxy_to_backend(backend_path=backend_path, head_only=head_only)
            return
        self.serve_static(path, head_only=head_only)

    def strip_base_path(self, raw_path: str) -> str:
        if not self.base_path or raw_path == self.base_path:
            return "/"
        if raw_path.startswith(f"{self.base_path}/"):
            return raw_path[len(self.base_path):] or "/"
        return raw_path

    def proxy_to_backend(self, *, backend_path: str, head_only: bool = False) -> None:
        body = b""
        content_length = self.headers.get("Content-Length")
        if content_length:
            body = self.rfile.read(int(content_length))

        headers = build_proxy_headers(self.headers, self.client_address[0])

        conn = http.client.HTTPConnection(self.backend_host, self.backend_port, timeout=120)
        try:
            conn.request(self.command, backend_path, body=body, headers=headers)
            resp = conn.getresponse()
            data = b"" if head_only else resp.read()
            self.send_response(resp.status, resp.reason)
            for key, value in resp.getheaders():
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.end_headers()
            if data:
                self.wfile.write(data)
        except OSError as exc:
            self.send_error(502, f"backend unavailable: {exc}")
        finally:
            conn.close()

    def serve_static(self, raw_path: str, *, head_only: bool = False) -> None:
        path = self.resolve_static_path(raw_path)
        is_asset_request = raw_path.startswith("/assets/")
        if not path.is_file():
            if is_asset_request:
                self.send_error(404)
                return
            path = self.static_root / "index.html"
        if not path.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = b"" if head_only else path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size if head_only else len(data)))
        if raw_path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=2592000, immutable")
        else:
            # The app shell must never outlive a build.  `npm run build` renames every
            # file under /assets/ with a fresh content hash, and index.html is the only
            # place those new names appear -- if the browser serves a cached index.html
            # it will keep requesting the previous build's asset names, which no longer
            # exist, and the page renders raw and half-loaded.
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def resolve_static_path(self, raw_path: str) -> Path:
        path = posixpath.normpath(unquote(raw_path.split("?", 1)[0]))
        if path in {"", "."}:
            path = "/"
        parts = [part for part in path.split("/") if part and part not in {".", ".."}]
        return self.static_root.joinpath(*parts).resolve()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve frontend/dist and proxy /api to the local backend without Docker/nginx.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:8204")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5204)
    parser.add_argument("--base-path", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    static_root = args.root.expanduser().resolve()
    if not (static_root / "index.html").is_file():
        raise SystemExit(f"frontend index.html not found under {static_root}; run npm run build first")
    backend = urlparse(args.backend)
    if backend.scheme not in {"http", ""}:
        raise SystemExit("Only http backend URLs are supported")
    host = backend.hostname or "127.0.0.1"
    port = backend.port or 8204
    FrontendProxyHandler.static_root = static_root
    FrontendProxyHandler.backend_host = host
    FrontendProxyHandler.backend_port = port
    FrontendProxyHandler.backend_scheme = backend.scheme or "http"
    base_path = "/" + args.base_path.strip("/") if args.base_path.strip("/") else ""
    FrontendProxyHandler.base_path = base_path
    server = ThreadingHTTPServer((args.host, args.port), FrontendProxyHandler)
    print(f"serving {static_root} on {args.host}:{args.port}, base {base_path or '/'}; proxying /api to {host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
