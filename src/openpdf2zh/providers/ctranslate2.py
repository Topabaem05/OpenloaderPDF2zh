from __future__ import annotations

from pathlib import Path

import ctranslate2
import sentencepiece as spm

from openpdf2zh.providers.base import BaseTranslator


class CTranslate2Translator(BaseTranslator):
    DIRECTIONAL_MODEL_DIRS = {
        "English": "quickmt-ko-en",
        "Korean": "quickmt-en-ko",
    }
    SUPPORTED_DIRECTIONAL_TARGET_LANGUAGES = frozenset(DIRECTIONAL_MODEL_DIRS)
    TARGET_LANGUAGE_TAGS = {
        "English": "eng_Latn",
        "Korean": "kor_Hang",
        "Japanese": "jpn_Jpan",
        "Simplified Chinese": "zho_Hans",
        "Traditional Chinese": "zho_Hant",
    }

    def __init__(self, model_dir: str, tokenizer_path: str) -> None:
        self._model_root = Path(model_dir).expanduser().resolve()
        self._tokenizer_path = tokenizer_path.strip()

        if not self._model_root.is_dir():
            raise RuntimeError(
                f"CTranslate2 model directory was not found: {self._model_root}. Check OPENPDF2ZH_CTRANSLATE2_MODEL_DIR."
            )
        if self._tokenizer_path:
            tokenizer_model_path = Path(self._tokenizer_path).expanduser().resolve()
            if not tokenizer_model_path.is_file():
                raise RuntimeError(
                    f"CTranslate2 tokenizer model was not found: {tokenizer_model_path}. Check OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH."
                )
        if not self._directional_assets_ready() and not self._tokenizer_path:
            raise RuntimeError(
                "CTranslate2 tokenizer model is missing. Set OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH or provide directional model subdirectories."
            )

        self._translator_cache: dict[str, ctranslate2.Translator] = {}
        self._source_tokenizer_cache: dict[str, spm.SentencePieceProcessor] = {}
        self._target_tokenizer_cache: dict[str, spm.SentencePieceProcessor] = {}

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        if self._directional_assets_ready():
            return self._translate_directional(text, target_language)
        return self._translate_multilingual(text, target_language)

    def _translate_multilingual(self, text: str, target_language: str) -> str:
        translator = self._ensure_multilingual_translator()
        tokenizer = self._ensure_multilingual_tokenizer()
        source_tokens = tokenizer.encode(text, out_type=str)
        source_tag = self._detect_source_language_tag(text)
        target_tag = self._resolve_target_language_tag(target_language)
        batch = [[source_tag, *source_tokens]]
        target_prefix = [[target_tag]]

        results = translator.translate_batch(
            batch,
            target_prefix=target_prefix,
            beam_size=1,
            max_batch_size=1,
            batch_type="examples",
        )
        if not results or not results[0].hypotheses:
            raise RuntimeError("CTranslate2 returned an empty translation result.")

        tokens = list(results[0].hypotheses[0])
        if tokens and tokens[0] == target_tag:
            tokens = tokens[1:]
        translated = tokenizer.decode(tokens).strip()
        if not translated:
            raise RuntimeError("CTranslate2 returned an empty translation output.")
        return translated

    def _translate_directional(self, text: str, target_language: str) -> str:
        translator, source_tokenizer, target_tokenizer = (
            self._ensure_directional_runtime(target_language)
        )
        source_tokens = source_tokenizer.encode(text, out_type=str)
        results = translator.translate_batch(
            [source_tokens],
            beam_size=1,
            max_batch_size=1,
            batch_type="examples",
        )
        if not results or not results[0].hypotheses:
            raise RuntimeError("CTranslate2 returned an empty translation result.")
        translated = target_tokenizer.decode(results[0].hypotheses[0]).strip()
        if not translated:
            raise RuntimeError("CTranslate2 returned an empty translation output.")
        return translated

    def _ensure_multilingual_translator(self) -> ctranslate2.Translator:
        key = "multilingual"
        if key not in self._translator_cache:
            self._translator_cache[key] = ctranslate2.Translator(
                str(self._model_root), device="cpu"
            )
        return self._translator_cache[key]

    def _ensure_multilingual_tokenizer(self) -> spm.SentencePieceProcessor:
        key = "multilingual"
        if key not in self._source_tokenizer_cache:
            tokenizer_model_path = Path(self._tokenizer_path).expanduser().resolve()
            if not tokenizer_model_path.is_file():
                raise RuntimeError(
                    f"CTranslate2 tokenizer model was not found: {tokenizer_model_path}. Check OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH."
                )
            tokenizer = spm.SentencePieceProcessor(model_file=str(tokenizer_model_path))
            self._source_tokenizer_cache[key] = tokenizer
            self._target_tokenizer_cache[key] = tokenizer
        return self._source_tokenizer_cache[key]

    def _ensure_directional_runtime(
        self, target_language: str
    ) -> tuple[
        ctranslate2.Translator, spm.SentencePieceProcessor, spm.SentencePieceProcessor
    ]:
        try:
            model_dir_name = self.DIRECTIONAL_MODEL_DIRS[target_language]
        except KeyError as exc:
            raise RuntimeError(
                "Unsupported CTranslate2 target language: "
                f"{target_language}. This local CTranslate2 setup currently supports only English and Korean."
            ) from exc

        if model_dir_name not in self._translator_cache:
            model_dir = self._model_root / model_dir_name
            self._translator_cache[model_dir_name] = ctranslate2.Translator(
                str(model_dir), device="cpu"
            )
            self._source_tokenizer_cache[model_dir_name] = spm.SentencePieceProcessor(
                model_file=str(model_dir / "src.spm.model")
            )
            self._target_tokenizer_cache[model_dir_name] = spm.SentencePieceProcessor(
                model_file=str(model_dir / "tgt.spm.model")
            )

        return (
            self._translator_cache[model_dir_name],
            self._source_tokenizer_cache[model_dir_name],
            self._target_tokenizer_cache[model_dir_name],
        )

    def _directional_assets_ready(self) -> bool:
        return all(
            (self._model_root / model_dir_name / required_file).exists()
            for model_dir_name in self.DIRECTIONAL_MODEL_DIRS.values()
            for required_file in ("model.bin", "src.spm.model", "tgt.spm.model")
        )

    def _resolve_target_language_tag(self, target_language: str) -> str:
        try:
            return self.TARGET_LANGUAGE_TAGS[target_language]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported CTranslate2 target language: {target_language}"
            ) from exc

    def _detect_source_language_tag(self, text: str) -> str:
        if any("가" <= char <= "힣" for char in text):
            return "kor_Hang"
        if any("ぁ" <= char <= "ゖ" or "ァ" <= char <= "ヺ" for char in text):
            return "jpn_Jpan"
        if any("一" <= char <= "鿿" for char in text):
            return "zho_Hans"
        return "eng_Latn"
