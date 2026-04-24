from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from openpdf2zh.config import AppSettings, OPENROUTER_PROVIDER
from openpdf2zh.models import PipelineResult
from openpdf2zh.utils.files import prepare_workspace
from openpdf2zh.webapp import create_app


def _pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        host="127.0.0.1",
        port=7860,
        workspace_root=tmp_path / "workspace",
        rate_limit_storage_path=str(tmp_path / "quota.sqlite3"),
    )


def test_root_serves_frontend_or_fallback_and_gradio_mount(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    root_response = client.get("/")
    gradio_response = client.get("/gradio")

    assert root_response.status_code == 200
    assert (
        "<div id=\"root\"></div>" in root_response.text
        or "OpenPDF2ZH frontend build is missing." in root_response.text
    )
    assert gradio_response.status_code == 200
    assert "OpenPDF2ZH" in gradio_response.text


def test_api_job_lifecycle_returns_artifacts(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    manager = app.state.job_manager

    def _run_inline(**kwargs):
        manager._run_job(**kwargs)

    def _fake_run(self, request, progress=None, quota_guard=None):
        if progress is not None:
            progress(0.15, desc="Parsing PDF with OpenDataLoader")
            progress(0.55, desc="Translating block 1/1 (page 1)")
            progress(0.9, desc="Rendering page 1/1")
        workspace = prepare_workspace(settings.workspace_root, request.input_pdf, job_id=request.job_id)
        workspace.public_dir.mkdir(parents=True, exist_ok=True)
        workspace.public_translated_pdf.write_bytes(b"%PDF translated")
        workspace.public_detected_boxes_pdf.write_bytes(b"%PDF detected")
        workspace.structured_json.write_text("{}", encoding="utf-8")
        workspace.translated_markdown.write_text("# result", encoding="utf-8")
        return PipelineResult(
            workspace=workspace,
            translated_unit_count=1,
            overflow_count=0,
            provider=request.provider,
            model=request.model,
            target_language=request.target_language,
            summary_markdown="done",
        )

    monkeypatch.setattr(manager, "_start_job_thread", _run_inline)
    monkeypatch.setattr("openpdf2zh.webapp.PipelineRunner.run", _fake_run)

    client = TestClient(app)
    create_response = client.post(
        "/api/jobs",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
        data={
            "provider": "ctranslate2",
            "target_language": "English",
            "page_mode": "first",
            "render_layout_engine": "legacy",
            "adjust_render_letter_spacing_for_overlap": "true",
        },
    )

    assert create_response.status_code == 202
    job_id = create_response.json()["job_id"]

    job_response = client.get(f"/api/jobs/{job_id}")
    payload = job_response.json()

    assert job_response.status_code == 200
    assert payload["status"] == "succeeded"
    assert payload["artifacts"]["translated_pdf"].endswith("/translated_mono.pdf")
    assert payload["artifacts"]["detected_boxes_pdf"].endswith("/detected_boxes.pdf")
    artifact_response = client.get(payload["artifacts"]["translated_pdf"])
    assert artifact_response.status_code == 200
    assert artifact_response.content == b"%PDF translated"


def test_api_job_reports_openrouter_key_failure(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    manager = app.state.job_manager

    def _run_inline(**kwargs):
        manager._run_job(**kwargs)

    def _fake_run(self, request, progress=None, quota_guard=None):
        raise RuntimeError("OpenRouter API key is required")

    monkeypatch.setattr(manager, "_start_job_thread", _run_inline)
    monkeypatch.setattr("openpdf2zh.webapp.PipelineRunner.run", _fake_run)

    client = TestClient(app)
    create_response = client.post(
        "/api/jobs",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
        data={
            "provider": OPENROUTER_PROVIDER,
            "target_language": "Korean",
            "page_mode": "first",
            "render_layout_engine": "legacy",
            "adjust_render_letter_spacing_for_overlap": "true",
            "openrouter_api_key": "sk-or-v1-test",
        },
    )
    assert create_response.status_code == 202

    job_id = create_response.json()["job_id"]
    job_response = client.get(f"/api/jobs/{job_id}")
    payload = job_response.json()

    assert payload["status"] == "failed"
    assert "OpenRouter" in payload["message_ko"]
    assert "OpenRouter" in payload["message_en"]


def test_api_rejects_missing_openrouter_key_before_queue(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
        data={
            "provider": OPENROUTER_PROVIDER,
            "target_language": "Korean",
            "page_mode": "first",
            "render_layout_engine": "legacy",
            "adjust_render_letter_spacing_for_overlap": "true",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "OpenRouter API key is required."
