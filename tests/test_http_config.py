from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openpdf2zh.http_config import configure_cors


def test_configure_cors_allows_only_configured_origins() -> None:
    app = FastAPI()
    configure_cors(app, ("https://openpdf2zh.vercel.app",))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    allowed = client.options(
        "/health",
        headers={
            "Origin": "https://openpdf2zh.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    blocked = client.get(
        "/health",
        headers={"Origin": "https://untrusted.example"},
    )

    assert allowed.status_code == 200
    assert (
        allowed.headers["access-control-allow-origin"]
        == "https://openpdf2zh.vercel.app"
    )
    assert "access-control-allow-origin" not in blocked.headers


def test_configure_cors_is_noop_when_no_origins_are_configured() -> None:
    app = FastAPI()
    configure_cors(app, ())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(app).get(
        "/health",
        headers={"Origin": "https://openpdf2zh.vercel.app"},
    )

    assert "access-control-allow-origin" not in response.headers
