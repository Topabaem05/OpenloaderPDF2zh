from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from openpdf2zh.config import AppSettings
from openpdf2zh.http_config import configure_cors
from openpdf2zh.utils.files import start_workspace_cleanup_worker


def create_server_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings.from_env()

    from openpdf2zh.webapp import create_app

    app = create_app(resolved_settings)
    configure_cors(app, resolved_settings.cors_allowed_origins)
    return app


def run_server(settings: AppSettings | None = None) -> None:
    resolved_settings = settings or AppSettings.from_env()
    start_workspace_cleanup_worker(
        resolved_settings.workspace_root,
        resolved_settings.workspace_retention_hours * 3600,
        resolved_settings.workspace_cleanup_interval_seconds,
    )
    app = create_server_app(resolved_settings)
    uvicorn.run(
        app,
        host=resolved_settings.host,
        port=resolved_settings.port,
    )


def main() -> int:
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
