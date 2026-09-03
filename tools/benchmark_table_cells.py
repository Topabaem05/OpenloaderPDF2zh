from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf as fitz

from openpdf2zh.config import AppSettings
from openpdf2zh.services.translation_service import TranslationService

DOCUMENTS = {
    "linux": {"pages": (21, 22, 32), "min_tables": (1, 1, 1), "min_cells": 5},
    "olmo": {"pages": (3, 6, 8), "min_tables": (2, 1, 1), "min_cells": 1},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_document(name: str, path: Path) -> tuple[dict[str, object], list[str]]:
    if not path.is_file():
        return {}, [f"{name}: missing input {path}"]
    specification = DOCUMENTS[name]
    service = TranslationService(AppSettings())
    failures: list[str] = []
    pages: list[dict[str, object]] = []
    with fitz.open(path) as document:
        for page_number, minimum_tables in zip(
            specification["pages"],
            specification["min_tables"],
        ):
            if page_number > len(document):
                failures.append(f"{name} page {page_number}: outside document")
                continue
            page = document[page_number - 1]
            source_lines = service._extract_source_lines(page)
            _, diagnostics = service._source_table_cells(
                page,
                page_number,
                [],
                source_lines,
                service._source_table_block_indexes(source_lines),
            )
            pages.append(diagnostics)
            if int(diagnostics["accepted_tables"]) < minimum_tables:
                failures.append(
                    f"{name} page {page_number}: expected at least "
                    f"{minimum_tables} tables"
                )
            if int(diagnostics["nonempty_cells"]) < specification["min_cells"]:
                failures.append(
                    f"{name} page {page_number}: expected at least "
                    f"{specification['min_cells']} nonempty cells"
                )
            if int(diagnostics["blank_pages"]):
                failures.append(f"{name} page {page_number}: blank page")
            for table in diagnostics["tables"]:
                if float(table["coverage"]) < 0.98:
                    failures.append(
                        f"{name} page {page_number}: table coverage below 0.98"
                    )
                if int(table["duplicate_words"]):
                    failures.append(
                        f"{name} page {page_number}: duplicate word ownership"
                    )
                if int(table["intersecting_cells"]):
                    failures.append(
                        f"{name} page {page_number}: intersecting cells"
                    )
    return {
        "name": name,
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "pages": pages,
    }, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--olmo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents: list[dict[str, object]] = []
    failures: list[str] = []
    for name in DOCUMENTS:
        document, document_failures = _inspect_document(name, getattr(args, name))
        if document:
            documents.append(document)
        failures.extend(document_failures)

    payload = {
        "schema_version": 1,
        "documents": documents,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
