from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _default_ctranslate2_model_dir() -> str:
    return str(Path(__file__).resolve().parents[2] / "models")


def _is_lfs_pointer(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            first_line = handle.readline()
    except OSError:
        return False
    return first_line.startswith(b"version https://git-lfs.github.com/spec/v1")


def _has_local_ctranslate2_models(model_dir: str) -> bool:
    model_root = Path(model_dir).expanduser()
    if not model_root.is_dir():
        return False
    directional_dirs = ("quickmt-ko-en", "quickmt-en-ko")
    if all(
        (model_root / name / "model.bin").exists()
        and not _is_lfs_pointer(model_root / name / "model.bin")
        for name in directional_dirs
    ):
        return True
    model_bin = model_root / "model.bin"
    return model_bin.exists() and not _is_lfs_pointer(model_bin)


def _default_provider_from_env(
    configured_provider: str | None,
    groq_api_key: str,
    ctranslate2_model_dir: str,
) -> str:
    configured = configured_provider.strip().lower() if configured_provider else ""
    has_groq = bool(groq_api_key.strip())
    has_local_ctranslate2 = _has_local_ctranslate2_models(ctranslate2_model_dir)

    if configured == "groq" and has_groq:
        return "groq"
    if configured == "ctranslate2" and has_local_ctranslate2:
        return "ctranslate2"
    if configured and configured not in {"groq", "ctranslate2"}:
        return configured
    if has_groq and not has_local_ctranslate2:
        return "groq"
    return "ctranslate2"


def _default_model_for_provider(
    provider: str,
    configured_model: str | None,
    configured_provider: str | None,
) -> str:
    configured_provider_value = (
        configured_provider.strip().lower() if configured_provider else ""
    )
    configured_model_value = configured_model.strip() if configured_model else ""

    if provider == "groq":
        if configured_provider_value == "groq" and configured_model_value:
            return configured_model_value
        return "llama-3.3-70b-versatile"
    if configured_model_value:
        return configured_model_value
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
        configured_provider = os.getenv("OPENPDF2ZH_DEFAULT_PROVIDER")
        configured_model = os.getenv("OPENPDF2ZH_DEFAULT_MODEL")
        default_provider = _default_provider_from_env(
            configured_provider,
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
                configured_model,
                configured_provider,
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
