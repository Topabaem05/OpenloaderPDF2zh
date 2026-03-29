from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _default_ctranslate2_model_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "models")


def _has_local_ctranslate2_models(model_dir: str) -> bool:
    model_root = Path(model_dir).expanduser()
    if not model_root.is_dir():
        return False
    directional_dirs = ("quickmt-ko-en", "quickmt-en-ko")
    if all((model_root / name / "model.bin").exists() for name in directional_dirs):
        return True
    return (model_root / "model.bin").exists()


def _default_provider_from_env(
    configured_provider: str | None,
    groq_api_key: str,
    ctranslate2_model_dir: str,
) -> str:
    if configured_provider:
        return configured_provider.strip().lower()
    if groq_api_key.strip() and not _has_local_ctranslate2_models(
        ctranslate2_model_dir
    ):
        return "groq"
    return "ctranslate2"


def _default_model_for_provider(provider: str, configured_model: str | None) -> str:
    if configured_model:
        return configured_model.strip()
    if provider == "groq":
        return "llama-3.3-70b-versatile"
    return "auto"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppSettings:
    host: str = "127.0.0.1"
    port: int = 7860
    workspace_root: Path = Path("workspace")
    default_provider: str = "ctranslate2"
    default_model: str = "auto"
    default_target_language: str = "Simplified Chinese"
    duplicate_box_iou_threshold: float = 0.85
    duplicate_box_iom_threshold: float = 0.9
    base_font_size: float = 10.0
    render_font_path: str = ""
    adjust_render_letter_spacing_for_overlap: bool = True
    job_queue_concurrency: int = 2
    job_queue_max_size: int = 8
    workspace_retention_hours: float = 24.0
    workspace_cleanup_interval_seconds: float = 600.0
    ctranslate2_model_dir: str = _default_ctranslate2_model_dir()
    ctranslate2_tokenizer_path: str = ""
    groq_api_key: str = ""

    @classmethod
    def from_env(cls) -> "AppSettings":
        railway_port = os.getenv("PORT")
        if railway_port:
            host = "0.0.0.0"
            port = int(railway_port)
        else:
            host = os.getenv("OPENPDF2ZH_HOST", "127.0.0.1")
            port = int(os.getenv("OPENPDF2ZH_PORT", "7860"))
        ctranslate2_model_dir = os.getenv(
            "OPENPDF2ZH_CTRANSLATE2_MODEL_DIR",
            _default_ctranslate2_model_dir(),
        ).strip()
        groq_api_key = os.getenv("GROQ_API_KEY", "")
        default_provider = _default_provider_from_env(
            os.getenv("OPENPDF2ZH_DEFAULT_PROVIDER"),
            groq_api_key,
            ctranslate2_model_dir,
        )

        return cls(
            host=host,
            port=port,
            workspace_root=Path(
                os.getenv("OPENPDF2ZH_WORKSPACE_ROOT", "workspace")
            ).resolve(),
            default_provider=default_provider,
            default_model=_default_model_for_provider(
                default_provider,
                os.getenv("OPENPDF2ZH_DEFAULT_MODEL"),
            ),
            default_target_language=os.getenv(
                "OPENPDF2ZH_DEFAULT_TARGET_LANGUAGE", "Simplified Chinese"
            ),
            duplicate_box_iou_threshold=float(
                os.getenv("OPENPDF2ZH_DUPLICATE_BOX_IOU_THRESHOLD", "0.85")
            ),
            duplicate_box_iom_threshold=float(
                os.getenv(
                    "OPENPDF2ZH_DUPLICATE_BOX_IOM_THRESHOLD",
                    os.getenv(
                        "OPENPDF2ZH_DUPLICATE_BOX_THRESHOLD",
                        os.getenv("OPENPDF2ZH_BOX_OVERLAP_THRESHOLD", "0.9"),
                    ),
                )
            ),
            base_font_size=float(os.getenv("OPENPDF2ZH_BASE_FONT_SIZE", "10.0")),
            render_font_path=os.getenv("OPENPDF2ZH_RENDER_FONT_PATH", "").strip(),
            adjust_render_letter_spacing_for_overlap=_as_bool(
                os.getenv("OPENPDF2ZH_ADJUST_RENDER_LETTER_SPACING_FOR_OVERLAP"),
                default=True,
            ),
            job_queue_concurrency=max(
                int(os.getenv("OPENPDF2ZH_JOB_QUEUE_CONCURRENCY", "2")),
                1,
            ),
            job_queue_max_size=max(
                int(os.getenv("OPENPDF2ZH_JOB_QUEUE_MAX_SIZE", "8")),
                1,
            ),
            workspace_retention_hours=max(
                float(os.getenv("OPENPDF2ZH_WORKSPACE_RETENTION_HOURS", "24")),
                0.0,
            ),
            workspace_cleanup_interval_seconds=max(
                float(
                    os.getenv(
                        "OPENPDF2ZH_WORKSPACE_CLEANUP_INTERVAL_SECONDS",
                        "600",
                    )
                ),
                30.0,
            ),
            ctranslate2_model_dir=ctranslate2_model_dir,
            ctranslate2_tokenizer_path=os.getenv(
                "OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH", ""
            ).strip(),
            groq_api_key=groq_api_key,
        )
