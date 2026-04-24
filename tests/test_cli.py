from __future__ import annotations

import tomllib
from pathlib import Path

from openpdf2zh.config import AppSettings
from openpdf2zh.models import JobWorkspace, PipelineResult


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_console_scripts() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["openpdf2zh"] == "openpdf2zh.cli:main"
    assert scripts["openpdf2zh-gradio"] == "openpdf2zh.cli:serve_main"
    assert scripts["openpdf2zh-translate"] == "openpdf2zh.cli:translate_main"


def test_pyproject_includes_package_asset_data() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = data["tool"]["setuptools"]["package-data"]

    assert package_data["openpdf2zh"] == ["assets/buy-me-a-coffee.svg"]


def test_main_defaults_to_serve(monkeypatch, tmp_path: Path) -> None:
    from openpdf2zh import cli

    calls: list[AppSettings] = []

    def fake_launch(settings: AppSettings | None = None) -> None:
        assert settings is not None
        calls.append(settings)

    monkeypatch.setattr(cli, "launch", fake_launch)

    exit_code = cli.main(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--workspace",
            str(tmp_path / "work"),
        ]
    )

    assert exit_code == 0
    assert calls[0].host == "0.0.0.0"
    assert calls[0].port == 9000
    assert calls[0].workspace_root == (tmp_path / "work").resolve()


def test_serve_subcommand_launches_gradio(monkeypatch, tmp_path: Path) -> None:
    from openpdf2zh import cli

    calls: list[AppSettings] = []

    def fake_launch(settings: AppSettings | None = None) -> None:
        assert settings is not None
        calls.append(settings)

    monkeypatch.setattr(cli, "launch", fake_launch)

    exit_code = cli.main(
        [
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "7777",
            "--workspace",
            str(tmp_path / "workspace"),
            "--provider",
            "openrouter",
            "--target-language",
            "Korean",
        ]
    )

    assert exit_code == 0
    assert calls[0].host == "127.0.0.1"
    assert calls[0].port == 7777
    assert calls[0].workspace_root == (tmp_path / "workspace").resolve()
    assert calls[0].default_provider == "groq"
    assert calls[0].default_target_language == "Korean"


def test_module_main_delegates_to_cli(monkeypatch) -> None:
    import openpdf2zh.__main__ as module_main

    calls: list[list[str]] = []

    def fake_main(argv=None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr(module_main, "main", fake_main)

    assert module_main.main(["--help"]) == 0
    assert calls == [["--help"]]


def test_shortcut_entrypoints_preserve_explicit_argv(monkeypatch) -> None:
    from openpdf2zh import cli

    calls: list[list[str]] = []

    def fake_main(argv=None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr(cli, "main", fake_main)

    assert cli.serve_main(["--help"]) == 0
    assert cli.translate_main(["sample.pdf", "--help"]) == 0
    assert calls == [["serve", "--help"], ["translate", "sample.pdf", "--help"]]


def _workspace(tmp_path: Path) -> JobWorkspace:
    root = tmp_path / "workspace" / "job-1"
    public_dir = tmp_path / "workspace" / "public" / "job-1"
    input_dir = root / "input"
    parsed_dir = root / "parsed"
    output_dir = root / "output"
    logs_dir = root / "logs"
    for path in (public_dir, input_dir, parsed_dir, output_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    source_pdf = input_dir / "sample.pdf"
    source_pdf.write_bytes(b"%PDF source")
    translated_pdf = output_dir / "translated_mono.pdf"
    translated_pdf.write_bytes(b"%PDF translated")
    detected_pdf = output_dir / "detected_boxes.pdf"
    detected_pdf.write_bytes(b"%PDF detected")
    result_md = output_dir / "result.md"
    result_md.write_text("# result", encoding="utf-8")
    structured_json = output_dir / "structured.json"
    structured_json.write_text("{}", encoding="utf-8")
    render_report_json = output_dir / "render_report.json"
    render_report_json.write_text("[]", encoding="utf-8")
    return JobWorkspace(
        job_id="job-1",
        root=root,
        public_dir=public_dir,
        input_pdf=source_pdf,
        parsed_dir=parsed_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        raw_json=parsed_dir / "raw.json",
        raw_markdown=parsed_dir / "raw.md",
        structured_json=structured_json,
        translated_markdown=result_md,
        translated_pdf=translated_pdf,
        public_translated_pdf=public_dir / "translated_mono.pdf",
        detected_boxes_pdf=detected_pdf,
        public_detected_boxes_pdf=public_dir / "detected_boxes.pdf",
        translation_units_jsonl=output_dir / "translation_units.jsonl",
        render_report_json=render_report_json,
        run_log=logs_dir / "run.log",
    )


def test_translate_subcommand_runs_pipeline_and_copies_outputs(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from openpdf2zh import cli

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF input")
    output_dir = tmp_path / "out"
    captured_requests = []

    def fake_run(self, request, progress=None, quota_guard=None):
        captured_requests.append(request)
        workspace = _workspace(tmp_path)
        return PipelineResult(
            workspace=workspace,
            translated_unit_count=3,
            overflow_count=0,
            provider=request.provider,
            model=request.model,
            target_language=request.target_language,
            summary_markdown="ok",
        )

    monkeypatch.setattr("openpdf2zh.cli.PipelineRunner.run", fake_run)

    exit_code = cli.main(
        [
            "translate",
            str(input_pdf),
            "--target-language",
            "Korean",
            "--provider",
            "ctranslate2",
            "--output-dir",
            str(output_dir),
            "--page-limit",
            "2",
        ]
    )

    assert exit_code == 0
    assert captured_requests[0].input_pdf == input_pdf.resolve()
    assert captured_requests[0].target_language == "Korean"
    assert captured_requests[0].provider == "ctranslate2"
    assert captured_requests[0].model == "auto"
    assert captured_requests[0].page_limit == 2
    assert (output_dir / "translated_mono.pdf").read_bytes() == b"%PDF translated"
    assert (output_dir / "detected_boxes.pdf").read_bytes() == b"%PDF detected"
    assert (output_dir / "result.md").read_text(encoding="utf-8") == "# result"
    assert (output_dir / "structured.json").read_text(encoding="utf-8") == "{}"
    assert (output_dir / "render_report.json").read_text(encoding="utf-8") == "[]"
    assert "translated_mono.pdf" in capsys.readouterr().out


def test_translate_rejects_non_pdf_input(tmp_path: Path) -> None:
    from openpdf2zh import cli

    input_file = tmp_path / "input.txt"
    input_file.write_text("not a pdf", encoding="utf-8")

    exit_code = cli.main(["translate", str(input_file)])

    assert exit_code == 2


def test_models_materialize_delegates_to_model_tool(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from openpdf2zh import cli

    calls: list[Path] = []

    def fake_materialize(target_root: Path) -> Path:
        calls.append(target_root)
        target_root.mkdir(parents=True)
        return target_root

    monkeypatch.setattr(cli, "materialize_quickmt_models", fake_materialize)

    exit_code = cli.main(
        [
            "models",
            "materialize",
            "--target-dir",
            str(tmp_path / "quickmt"),
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path / "quickmt").resolve()]
    assert str(tmp_path / "quickmt") in capsys.readouterr().out
