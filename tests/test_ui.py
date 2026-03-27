import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.ui import (
    _build_runtime_settings,
    _parse_ocr_langs,
    _serialize_ocr_langs,
)


def test_parse_ocr_langs_splits_comma_separated_values() -> None:
    assert _parse_ocr_langs("ko,en,zh") == ["ko", "en", "zh"]


def test_serialize_ocr_langs_joins_selected_values() -> None:
    assert _serialize_ocr_langs(["ko", "en", "zh"]) == "ko,en,zh"


def test_build_runtime_settings_overrides_libretranslate_server() -> None:
    settings = AppSettings(libretranslate_url="http://127.0.0.1:5000")

    runtime_settings = _build_runtime_settings(
        settings,
        "libretranslate",
        "http://localhost:5050/",
        "",
    )

    assert runtime_settings.libretranslate_url == "http://localhost:5050"
    assert runtime_settings.libretranslate_api_key == ""


def test_build_runtime_settings_requires_url_for_libretranslate() -> None:
    with pytest.raises(Exception, match="LibreTranslate server URL"):
        _build_runtime_settings(AppSettings(), "libretranslate", "  ", "")
