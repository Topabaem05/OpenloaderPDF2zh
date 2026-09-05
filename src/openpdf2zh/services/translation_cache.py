from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from openpdf2zh.translation.contracts import TranslationRequestItem


class TranslationCache:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def key_for(
        self,
        item: TranslationRequestItem,
        *,
        provider: str,
        model: str,
    ) -> str:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "provider": provider.strip().lower(),
            "model": model.strip(),
            "target_language": item.target_language,
            "text": item.text,
            "section_title": item.section_title,
            "paragraph_text": item.paragraph_text,
            "previous_text": item.previous_text,
            "next_text": item.next_text,
            "glossary": sorted(item.glossary.items()),
            "protected_tokens": sorted(item.protected_tokens.items()),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(
        self,
        item: TranslationRequestItem,
        *,
        provider: str,
        model: str,
    ) -> str | None:
        cache_key = self.key_for(item, provider=provider, model=model)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT translated_text FROM translation_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def put(
        self,
        item: TranslationRequestItem,
        *,
        provider: str,
        model: str,
        translated_text: str,
    ) -> None:
        value = translated_text.strip()
        if not value:
            raise ValueError("translated_text must not be empty")
        cache_key = self.key_for(item, provider=provider, model=model)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO translation_cache(cache_key, translated_text)
                VALUES (?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    translated_text = excluded.translated_text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (cache_key, value),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        if self.path.exists() and self.path.is_dir():
            raise IsADirectoryError(f"Translation cache path is a directory: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_cache (
                cache_key TEXT PRIMARY KEY,
                translated_text TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return connection
