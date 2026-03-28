from pathlib import Path

import pytest

from openpdf2zh.config import AppSettings
from openpdf2zh.providers.ctranslate2 import CTranslate2Translator
from openpdf2zh.services.translation_service import TranslationService


class _FakeResult:
    def __init__(self, tokens: list[str]) -> None:
        self.hypotheses = [tokens]


class _FakeTranslator:
    def __init__(self, model_dir: str, device: str = "cpu") -> None:
        self.model_dir = model_dir
        self.calls: list[dict[str, object]] = []

    def translate_batch(self, batch, **kwargs):
        self.calls.append({"batch": batch, **kwargs})
        return [_FakeResult(["eng_Latn", "▁Hello", "▁world"])]


class _FakeSentencePiece:
    def __init__(self, model_file: str) -> None:
        self.model_file = model_file

    def encode(self, text: str, out_type=str):
        return ["▁안녕하세요"] if "안녕하세요" in text else ["▁Hello", "▁world"]

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens).replace("▁", "").strip()


class _DirectionalFakeTranslator:
    def __init__(self, model_dir: str, device: str = "cpu") -> None:
        self.model_dir = model_dir
        self.calls: list[dict[str, object]] = []

    def translate_batch(self, batch, **kwargs):
        self.calls.append({"batch": batch, **kwargs})
        if "quickmt-ko-en" in self.model_dir:
            return [_FakeResult(["▁Hello", "▁world"])]
        return [_FakeResult(["▁안녕", "하세요"])]


class _DirectionalSentencePiece:
    def __init__(self, model_file: str) -> None:
        self.model_file = model_file

    def encode(self, text: str, out_type=str):
        if "src.spm.model" in self.model_file and any(
            "가" <= char <= "힣" for char in text
        ):
            return ["▁안녕하세요"]
        return ["▁Hello", "▁world"]

    def decode(self, tokens: list[str]) -> str:
        return " ".join(tokens).replace("▁", "").strip()


def test_build_translator_returns_ctranslate2_provider(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    tokenizer = tmp_path / "tokenizer.model"
    tokenizer.write_text("fake", encoding="utf-8")
    service = TranslationService(
        AppSettings(
            ctranslate2_model_dir=str(model_dir),
            ctranslate2_tokenizer_path=str(tokenizer),
        )
    )

    translator = service._build_translator("ctranslate2")

    assert isinstance(translator, CTranslate2Translator)


def test_ctranslate2_missing_assets_raise_actionable_errors(tmp_path: Path) -> None:
    tokenizer = tmp_path / "tokenizer.model"
    tokenizer.write_text("fake", encoding="utf-8")

    with pytest.raises(RuntimeError, match="model directory was not found"):
        CTranslate2Translator(str(tmp_path / "missing-model"), str(tokenizer))

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    with pytest.raises(RuntimeError, match="tokenizer model was not found"):
        CTranslate2Translator(str(model_dir), str(tmp_path / "missing-tokenizer.model"))


def test_ctranslate2_translate_uses_sentencepiece_and_target_prefix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    tokenizer = tmp_path / "tokenizer.model"
    tokenizer.write_text("fake", encoding="utf-8")

    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.Translator",
        _FakeTranslator,
    )
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.spm.SentencePieceProcessor",
        _FakeSentencePiece,
    )

    translator = CTranslate2Translator(str(model_dir), str(tokenizer))
    translated = translator.translate(
        "안녕하세요", target_language="English", model="auto"
    )

    assert translated == "Hello world"
    translator_cache = translator._translator_cache["multilingual"]
    assert translator_cache.calls[0]["batch"] == [["kor_Hang", "▁안녕하세요"]]
    assert translator_cache.calls[0]["target_prefix"] == [["eng_Latn"]]


def test_ctranslate2_translate_uses_directional_model_layout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "models"
    ko_en = root_dir / "quickmt-ko-en"
    en_ko = root_dir / "quickmt-en-ko"
    for model_dir in (ko_en, en_ko):
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").write_text("fake", encoding="utf-8")
        (model_dir / "src.spm.model").write_text("fake", encoding="utf-8")
        (model_dir / "tgt.spm.model").write_text("fake", encoding="utf-8")

    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.Translator",
        _DirectionalFakeTranslator,
    )
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.spm.SentencePieceProcessor",
        _DirectionalSentencePiece,
    )

    translator = CTranslate2Translator(str(root_dir), "")

    translated_en = translator.translate(
        "안녕하세요", target_language="English", model="auto"
    )
    translated_ko = translator.translate(
        "Hello world", target_language="Korean", model="auto"
    )

    assert translated_en == "Hello world"
    assert translated_ko == "안녕 하세요"


def test_ctranslate2_reports_unsupported_directional_target_language(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "models"
    ko_en = root_dir / "quickmt-ko-en"
    en_ko = root_dir / "quickmt-en-ko"
    for model_dir in (ko_en, en_ko):
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").write_text("fake", encoding="utf-8")
        (model_dir / "src.spm.model").write_text("fake", encoding="utf-8")
        (model_dir / "tgt.spm.model").write_text("fake", encoding="utf-8")

    translator = CTranslate2Translator(str(root_dir), "")

    with pytest.raises(
        RuntimeError, match="currently supports only English and Korean"
    ):
        translator.translate(
            "안녕하세요", target_language="Simplified Chinese", model="auto"
        )
