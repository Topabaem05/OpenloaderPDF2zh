from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppSettings:
    host: str = "127.0.0.1"
    port: int = 7860
    workspace_root: Path = Path("workspace")
    default_provider: str = "openrouter"
    default_model: str = "openrouter/auto"
    default_target_language: str = "Simplified Chinese"
    default_ocr_langs: str = "ko,en,ch_sim"
    hybrid_backend: str = "docling-fast"
    hybrid_port: int = 5002
    hybrid_timeout_ms: int = 120000
    manage_hybrid_backend: bool = True
    base_font_size: float = 10.0
    openrouter_api_key: str = ""
    groq_api_key: str = ""
    libretranslate_url: str = "http://127.0.0.1:5000"
    libretranslate_api_key: str = ""
    openrouter_app_name: str = "OpenPDF2ZH"
    openrouter_app_url: str = ""

    @classmethod
    def from_env(cls) -> "AppSettings":
        return cls(
            host=os.getenv("OPENPDF2ZH_HOST", "127.0.0.1"),
            port=int(os.getenv("OPENPDF2ZH_PORT", "7860")),
            workspace_root=Path(
                os.getenv("OPENPDF2ZH_WORKSPACE_ROOT", "workspace")
            ).resolve(),
            default_provider=os.getenv("OPENPDF2ZH_DEFAULT_PROVIDER", "openrouter"),
            default_model=os.getenv("OPENPDF2ZH_DEFAULT_MODEL", "openrouter/auto"),
            default_target_language=os.getenv(
                "OPENPDF2ZH_DEFAULT_TARGET_LANGUAGE", "Simplified Chinese"
            ),
            default_ocr_langs=os.getenv("OPENPDF2ZH_DEFAULT_OCR_LANGS", "ko,en,ch_sim"),
            hybrid_backend=os.getenv("OPENPDF2ZH_HYBRID_BACKEND", "docling-fast"),
            hybrid_port=int(os.getenv("OPENPDF2ZH_HYBRID_PORT", "5002")),
            hybrid_timeout_ms=int(os.getenv("OPENPDF2ZH_HYBRID_TIMEOUT_MS", "120000")),
            manage_hybrid_backend=_as_bool(
                os.getenv("OPENPDF2ZH_MANAGE_HYBRID_BACKEND"), default=True
            ),
            base_font_size=float(os.getenv("OPENPDF2ZH_BASE_FONT_SIZE", "10.0")),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            libretranslate_url=os.getenv(
                "OPENPDF2ZH_LIBRETRANSLATE_URL", "http://127.0.0.1:5000"
            ).strip(),
            libretranslate_api_key=os.getenv("LIBRETRANSLATE_API_KEY", "").strip(),
            openrouter_app_name=os.getenv(
                "OPENPDF2ZH_OPENROUTER_APP_NAME", "OpenPDF2ZH"
            ),
            openrouter_app_url=os.getenv("OPENPDF2ZH_OPENROUTER_APP_URL", ""),
        )
