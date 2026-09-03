from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MAX_BODY_BYTES = 10 * 1024 * 1024


def with_reasoning_disabled(body: bytes) -> bytes:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError("request body must be a JSON object")
    payload.setdefault("reasoning_effort", "none")
    payload.setdefault("max_tokens", 2048)
    return json.dumps(payload).encode()


class ProxyHandler(BaseHTTPRequestHandler):
    upstream = ""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, b'{"status":"ok"}')
        else:
            self._reply(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._reply(404, b'{"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("invalid Content-Length")
            request = Request(
                self.upstream,
                data=with_reasoning_disabled(self.rfile.read(length)),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=600) as response:
                self._reply(response.status, response.read())
        except HTTPError as exc:
            self._reply(exc.code, exc.read())
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._reply(502, json.dumps({"error": str(exc)}).encode())

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument(
        "--upstream",
        default="http://127.0.0.1:8081/v1/chat/completions",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert json.loads(with_reasoning_disabled(b'{"model":"test"}')) == {
            "model": "test",
            "reasoning_effort": "none",
            "max_tokens": 2048,
        }
        return
    ProxyHandler.upstream = args.upstream
    ThreadingHTTPServer(("127.0.0.1", args.port), ProxyHandler).serve_forever()


if __name__ == "__main__":
    main()
