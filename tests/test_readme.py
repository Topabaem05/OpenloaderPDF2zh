from __future__ import annotations

from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_installation_paths_and_cli_examples() -> None:
    text = README.read_text(encoding="utf-8")

    required = [
        "pip install openpdf2zh-gradio",
        "pipx install openpdf2zh-gradio",
        "pip install -e .[dev]",
        "docker compose -f deploy/docker/docker-compose.yml up --build",
        "openpdf2zh serve",
        "openpdf2zh-gradio",
        "openpdf2zh translate sample.pdf --target-language Korean --output-dir out",
        "openpdf2zh-translate sample.pdf --target-language Korean --output-dir out",
        "openpdf2zh models materialize",
        "OPENPDF2ZH_HOST_MODEL_DIR=/absolute/path/to/models",
    ]
    for snippet in required:
        assert snippet in text
