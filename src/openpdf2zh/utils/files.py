from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpdf2zh.models import JobWorkspace


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "document"


def make_job_id(file_stem: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(file_stem)}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_workspace(root: Path, source_pdf: Path) -> JobWorkspace:
    job_id = make_job_id(source_pdf.stem)
    workspace_dir = ensure_dir(root / job_id)
    input_dir = ensure_dir(workspace_dir / "input")
    parsed_dir = ensure_dir(workspace_dir / "parsed")
    output_dir = ensure_dir(workspace_dir / "output")
    logs_dir = ensure_dir(workspace_dir / "logs")
    copied_pdf = input_dir / source_pdf.name
    shutil.copy2(source_pdf, copied_pdf)
    return JobWorkspace(
        job_id=job_id,
        root=workspace_dir,
        input_pdf=copied_pdf,
        parsed_dir=parsed_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        raw_json=parsed_dir / "raw.json",
        raw_markdown=parsed_dir / "raw.md",
        structured_json=output_dir / "structured.json",
        translated_markdown=output_dir / "result.md",
        translated_pdf=output_dir / "translated_mono.pdf",
        detected_boxes_pdf=output_dir / "detected_boxes.pdf",
        translation_units_jsonl=output_dir / "translation_units.jsonl",
        render_report_json=output_dir / "render_report.json",
        run_log=logs_dir / "run.log",
    )


def copy_first_matching(
    source_dir: Path, target_path: Path, suffixes: Iterable[str]
) -> Path:
    suffix_set = {suffix.lower() for suffix in suffixes}
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffix_set:
            shutil.copy2(path, target_path)
            return target_path
    raise FileNotFoundError(
        f"No file with suffix {sorted(suffix_set)} found under {source_dir}"
    )


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_run_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


@contextmanager
def run_log_heartbeat(
    path: Path,
    phase: str,
    *,
    interval_seconds: float = 10.0,
    context_provider: Callable[[], str] | None = None,
) -> Iterator[None]:
    stop_event = threading.Event()
    started_at = time.monotonic()

    def emit_heartbeat() -> None:
        while not stop_event.wait(interval_seconds):
            elapsed_seconds = int(time.monotonic() - started_at)
            extra = ""
            if context_provider is not None:
                try:
                    context = context_provider().strip()
                except Exception:
                    context = ""
                if context:
                    extra = f" {context}"
            append_run_log(
                path,
                f"heartbeat phase={phase} elapsed={elapsed_seconds}s{extra}",
            )

    worker = threading.Thread(
        target=emit_heartbeat,
        name=f"run-log-heartbeat-{phase}",
        daemon=True,
    )
    worker.start()
    try:
        yield
    finally:
        stop_event.set()
        worker.join(timeout=1.0)
