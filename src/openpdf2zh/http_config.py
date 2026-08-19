from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def configure_cors(app: FastAPI, origins: tuple[str, ...]) -> None:
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
