from __future__ import annotations

from pathlib import Path

from openpdf2zh.providers.ctranslate2 import CTranslate2Translator
from openpdf2zh.translation.contracts import TranslationRequestItem


class _FakeResult:
    def __init__(self, tokens: list[str]) -> None:
        self.hypotheses = [tokens]


class _FakeTranslator:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.batch: list[list[str]] | None = None
        self.target_prefix: list[list[str]] | None = None
        self.call_count = 0

    def translate_batch(self, batch: list[list[str]], **kwargs: object) -> list[_FakeResult]:
        self.call_count += 1
        self.batch = batch
        self.target_prefix = kwargs.get("target_prefix")  # type: ignore[assignment]
        return [_FakeResult(list(self.tokens)) for _ in batch]


class _FakeSentencePieceTokenizer:
    def __init__(self) -> None:
        self.encoded_texts: list[str] = []
        self.decoded_tokens: list[list[str]] = []

    def encode(self, text: str, out_type: type[str] = str) -> list[str]:
        assert out_type is str
        self.encoded_texts.append(text)
        return ["hello", "world"]

    def decode(self, tokens: list[str]) -> str:
        self.decoded_tokens.append(tokens)
        return "sentencepiece-decoded"


class _FakeTransformersTokenizer:
    def __init__(self) -> None:
        self.src_lang = "eng_Latn"
        self.encoded_texts: list[str] = []
        self.converted_ids: list[list[int]] = []
        self.converted_tokens: list[list[str]] = []
        self.decoded_ids: list[list[int]] = []

    def encode(self, text: str) -> list[int]:
        self.encoded_texts.append(text)
        return [101, 102, 103]

    def convert_ids_to_tokens(self, token_ids: list[int]) -> list[str]:
        self.converted_ids.append(token_ids)
        return ["eng_Latn", "tok_a", "tok_b"]

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        self.converted_tokens.append(tokens)
        return [201, 202]

    def decode(
        self,
        token_ids: list[int],
        *,
        skip_special_tokens: bool,
        clean_up_tokenization_spaces: bool,
    ) -> str:
        assert skip_special_tokens is True
        assert clean_up_tokenization_spaces is True
        self.decoded_ids.append(token_ids)
        return "transformers-decoded"


def _write_nllb_tokenizer_assets(model_dir: Path) -> None:
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer_config.json").write_text(
        '{"tokenizer_class":"NllbTokenizer"}',
        encoding="utf-8",
    )
    (model_dir / "sentencepiece.bpe.model").write_text("stub", encoding="utf-8")


def test_sentencepiece_multilingual_backend_is_used_when_external_tokenizer_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    tokenizer_path = tmp_path / "tokenizer.model"
    tokenizer_path.write_text("stub", encoding="utf-8")
    fake_tokenizer = _FakeSentencePieceTokenizer()
    fake_translator = _FakeTranslator(["kor_Hang", "tok_x", "tok_y"])

    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.spm.SentencePieceProcessor",
        lambda model_file: fake_tokenizer,
    )

    translator = CTranslate2Translator(str(model_dir), str(tokenizer_path))
    monkeypatch.setattr(
        translator,
        "_ensure_multilingual_translator",
        lambda: fake_translator,
    )

    translated = translator.translate(
        "Hello world",
        target_language="Korean",
        model="auto",
    )

    assert translated == "sentencepiece-decoded"
    assert fake_translator.batch == [["eng_Latn", "hello", "world"]]
    assert fake_translator.target_prefix == [["kor_Hang"]]
    assert fake_tokenizer.decoded_tokens == [["tok_x", "tok_y"]]


def test_translate_many_uses_single_multilingual_translate_batch_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    tokenizer_path = tmp_path / "tokenizer.model"
    tokenizer_path.write_text("stub", encoding="utf-8")
    fake_tokenizer = _FakeSentencePieceTokenizer()
    fake_translator = _FakeTranslator(["kor_Hang", "tok_x", "tok_y"])
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.spm.SentencePieceProcessor",
        lambda model_file: fake_tokenizer,
    )

    translator = CTranslate2Translator(str(model_dir), str(tokenizer_path))
    monkeypatch.setattr(
        translator,
        "_ensure_multilingual_translator",
        lambda: fake_translator,
    )
    items = [
        TranslationRequestItem("r1", "First sentence", "Korean"),
        TranslationRequestItem("r2", "Second sentence", "Korean"),
    ]

    translated = translator.translate_many(items, model="auto")

    assert translated == ["sentencepiece-decoded", "sentencepiece-decoded"]
    assert fake_translator.call_count == 1
    assert fake_translator.batch == [
        ["eng_Latn", "hello", "world"],
        ["eng_Latn", "hello", "world"],
    ]
    assert fake_translator.target_prefix == [["kor_Hang"], ["kor_Hang"]]


def test_nllb_assets_enable_transformers_multilingual_backend_without_external_tokenizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "nllb"
    model_dir.mkdir()
    _write_nllb_tokenizer_assets(model_dir)
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.__version__",
        "4.7.1",
    )

    translator = CTranslate2Translator(str(model_dir), "")

    assert translator._use_transformers_multilingual_tokenizer is True


def test_transformers_multilingual_backend_is_used_for_nllb_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "nllb"
    model_dir.mkdir()
    _write_nllb_tokenizer_assets(model_dir)
    fake_tokenizer = _FakeTransformersTokenizer()
    fake_translator = _FakeTranslator(["kor_Hang", "tok_k1", "tok_k2"])
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.__version__",
        "4.7.1",
    )

    translator = CTranslate2Translator(str(model_dir), "")
    monkeypatch.setattr(
        translator,
        "_load_transformers_multilingual_tokenizer",
        lambda: fake_tokenizer,
    )
    monkeypatch.setattr(
        translator,
        "_ensure_multilingual_translator",
        lambda: fake_translator,
    )

    translated = translator.translate(
        "Hello world",
        target_language="Korean",
        model="auto",
    )

    assert translated == "transformers-decoded"
    assert fake_tokenizer.src_lang == "eng_Latn"
    assert fake_translator.batch == [["eng_Latn", "eng_Latn", "tok_a", "tok_b"]]
    assert fake_translator.target_prefix == [["kor_Hang"]]
    assert fake_tokenizer.converted_tokens == [["tok_k1", "tok_k2"]]
    assert fake_tokenizer.decoded_ids == [[201, 202]]


def test_transformers_multilingual_backend_updates_source_language_tag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "nllb"
    model_dir.mkdir()
    _write_nllb_tokenizer_assets(model_dir)
    fake_tokenizer = _FakeTransformersTokenizer()
    fake_translator = _FakeTranslator(["kor_Hang", "tok_k1"])
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.__version__",
        "4.7.1",
    )

    translator = CTranslate2Translator(str(model_dir), "")
    monkeypatch.setattr(
        translator,
        "_load_transformers_multilingual_tokenizer",
        lambda: fake_tokenizer,
    )
    monkeypatch.setattr(
        translator,
        "_ensure_multilingual_translator",
        lambda: fake_translator,
    )

    translator.translate(
        "항공역학",
        target_language="English",
        model="auto",
    )

    assert fake_tokenizer.src_lang == "kor_Hang"
    assert fake_translator.target_prefix == [["eng_Latn"]]


def test_nllb_assets_raise_clear_error_with_old_ctranslate2_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "nllb"
    model_dir.mkdir()
    _write_nllb_tokenizer_assets(model_dir)
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.__version__",
        "4.6.0",
    )

    try:
        CTranslate2Translator(str(model_dir), "")
    except RuntimeError as exc:
        assert "ctranslate2>=4.7.1" in str(exc)
    else:
        raise AssertionError("Expected a clear version error for old ctranslate2.")


def test_single_direction_bundle_uses_configured_gpu_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_root = tmp_path / "models"
    model_dir = model_root / "quickmt-en-ko"
    model_dir.mkdir(parents=True)
    for name in ("model.bin", "src.spm.model", "tgt.spm.model"):
        (model_dir / name).write_bytes(b"stub")
    constructor_calls: list[tuple[str, str, str]] = []

    def build_translator(
        path: str,
        *,
        device: str,
        compute_type: str,
    ) -> _FakeTranslator:
        constructor_calls.append((path, device, compute_type))
        return _FakeTranslator(["translated"])

    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.ctranslate2.Translator",
        build_translator,
    )
    monkeypatch.setattr(
        "openpdf2zh.providers.ctranslate2.spm.SentencePieceProcessor",
        lambda model_file: _FakeSentencePieceTokenizer(),
    )

    translator = CTranslate2Translator(
        str(model_root),
        "",
        device="cuda",
        compute_type="float16",
    )
    translator._ensure_directional_runtime("Korean")

    assert constructor_calls == [(str(model_dir), "cuda", "float16")]
