from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import ctranslate2
import sentencepiece as spm

from openpdf2zh.providers.base import BaseTranslator


class CTranslate2Translator(BaseTranslator):
    MIN_TRANSFORMERS_MULTILINGUAL_CTRANSLATE2_VERSION = (4, 7, 1)
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
        self._use_transformers_multilingual_tokenizer = (
            self._has_transformers_multilingual_tokenizer_assets()
        )

        if not self._model_root.is_dir():
            raise RuntimeError(
                f"CTranslate2 model directory was not found: {self._model_root}. Check OPENPDF2ZH_CTRANSLATE2_MODEL_DIR."
            )
        if self._tokenizer_path and not self._use_transformers_multilingual_tokenizer:
            tokenizer_model_path = Path(self._tokenizer_path).expanduser().resolve()
            if not tokenizer_model_path.is_file():
                raise RuntimeError(
                    f"CTranslate2 tokenizer model was not found: {tokenizer_model_path}. Check OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH."
                )
        self._validate_runtime_support()
        pointer_model = self._first_directional_lfs_pointer()
        if pointer_model is not None:
            self._raise_for_lfs_pointer(pointer_model)
        if (
            not self._directional_assets_ready()
            and not self._tokenizer_path
            and not self._use_transformers_multilingual_tokenizer
        ):
            raise RuntimeError(
                "CTranslate2 tokenizer assets are missing. Set OPENPDF2ZH_CTRANSLATE2_TOKENIZER_PATH, provide bundled multilingual tokenizer files, or provide directional model subdirectories."
            )

        self._translator_cache: dict[str, ctranslate2.Translator] = {}
        self._source_tokenizer_cache: dict[str, spm.SentencePieceProcessor] = {}
        self._target_tokenizer_cache: dict[str, spm.SentencePieceProcessor] = {}
        self._multilingual_tokenizer_cache: dict[str, Any] = {}

    def _validate_runtime_support(self) -> None:
        if not self._use_transformers_multilingual_tokenizer:
            return
        current_version = self._parse_version_tuple(ctranslate2.__version__)
        if current_version >= self.MIN_TRANSFORMERS_MULTILINGUAL_CTRANSLATE2_VERSION:
            return

        required_version = ".".join(
            str(part)
            for part in self.MIN_TRANSFORMERS_MULTILINGUAL_CTRANSLATE2_VERSION
        )
        raise RuntimeError(
            "NLLB-style CTranslate2 bundles require "
            f"ctranslate2>={required_version}. Current version: "
            f"{ctranslate2.__version__}. Upgrade ctranslate2 and retry."
        )

    def translate(self, text: str, *, target_language: str, model: str) -> str:
        if self._directional_assets_ready():
            return self._translate_directional(text, target_language)
        return self._translate_multilingual(text, target_language)

    def _translate_multilingual(self, text: str, target_language: str) -> str:
        translator = self._ensure_multilingual_translator()
        source_tag = self._detect_source_language_tag(text)
        target_tag = self._resolve_target_language_tag(target_language)
        source_tokens = self._encode_multilingual_source_tokens(text, source_tag)
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
        translated = self._decode_multilingual_tokens(tokens).strip()
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

    def _encode_multilingual_source_tokens(
        self,
        text: str,
        source_language_tag: str,
    ) -> list[str]:
        if self._use_transformers_multilingual_tokenizer:
            tokenizer = self._ensure_transformers_multilingual_tokenizer()
            tokenizer.src_lang = source_language_tag
            token_ids = tokenizer.encode(text)
            return list(tokenizer.convert_ids_to_tokens(token_ids))

        tokenizer = self._ensure_multilingual_tokenizer()
        return tokenizer.encode(text, out_type=str)

    def _decode_multilingual_tokens(self, tokens: list[str]) -> str:
        if self._use_transformers_multilingual_tokenizer:
            tokenizer = self._ensure_transformers_multilingual_tokenizer()
            token_ids = tokenizer.convert_tokens_to_ids(tokens)
            return tokenizer.decode(
                token_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )

        tokenizer = self._ensure_multilingual_tokenizer()
        return tokenizer.decode(tokens)

    def _ensure_transformers_multilingual_tokenizer(self) -> Any:
        key = "multilingual"
        if key not in self._multilingual_tokenizer_cache:
            self._multilingual_tokenizer_cache[key] = (
                self._load_transformers_multilingual_tokenizer()
            )
        return self._multilingual_tokenizer_cache[key]

    def _load_transformers_multilingual_tokenizer(self) -> Any:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Transformers tokenizer assets were detected for the CTranslate2 model, but `transformers` is not installed."
            ) from exc

        return AutoTokenizer.from_pretrained(
            str(self._model_root),
            src_lang="eng_Latn",
            clean_up_tokenization_spaces=True,
            use_fast=False,
        )

    def _has_transformers_multilingual_tokenizer_assets(self) -> bool:
        tokenizer_config_path = self._model_root / "tokenizer_config.json"
        model_config_path = self._model_root / "config.json"
        sentencepiece_path = self._model_root / "sentencepiece.bpe.model"
        if (
            not tokenizer_config_path.is_file()
            or not model_config_path.is_file()
            or not sentencepiece_path.is_file()
        ):
            return False

        try:
            payload = json.loads(tokenizer_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        tokenizer_class = str(payload.get("tokenizer_class", "")).strip()
        return tokenizer_class == "NllbTokenizer"

    @staticmethod
    def _parse_version_tuple(raw_version: str) -> tuple[int, int, int]:
        parts: list[int] = []
        for segment in raw_version.split("."):
            digits = "".join(char for char in segment if char.isdigit())
            if not digits:
                break
            parts.append(int(digits))
            if len(parts) == 3:
                break
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])

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
            model_dir = self._directional_root_dir() / model_dir_name
            self._raise_for_lfs_pointer(model_dir / "model.bin")
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
        directional_root = self._directional_root_dir()
        return all(
            (directional_root / model_dir_name / required_file).exists()
            and not (
                required_file == "model.bin"
                and self._is_lfs_pointer(
                    directional_root / model_dir_name / required_file
                )
            )
            for model_dir_name in self.DIRECTIONAL_MODEL_DIRS.values()
            for required_file in ("model.bin", "src.spm.model", "tgt.spm.model")
        )

    def _directional_root_dir(self) -> Path:
        if self._model_root.name in self.DIRECTIONAL_MODEL_DIRS.values():
            return self._model_root.parent
        return self._model_root

    def _first_directional_lfs_pointer(self) -> Path | None:
        directional_root = self._directional_root_dir()
        for model_dir_name in self.DIRECTIONAL_MODEL_DIRS.values():
            candidate = directional_root / model_dir_name / "model.bin"
            if self._is_lfs_pointer(candidate):
                return candidate
        return None

    def _raise_for_lfs_pointer(self, path: Path) -> None:
        if self._is_lfs_pointer(path):
            raise RuntimeError(
                f"CTranslate2 model file is still a Git LFS pointer, not the real binary: {path}. "
                "On Railway, run the build-time quickmt Hugging Face materialization step so the real local model files are downloaded into the image."
            )

    def _is_lfs_pointer(self, path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                first_line = handle.readline()
        except OSError:
            return False
        return first_line.startswith(b"version https://git-lfs.github.com/spec/v1")

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
