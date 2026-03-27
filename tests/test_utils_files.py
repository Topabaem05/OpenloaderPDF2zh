import time
from pathlib import Path

from openpdf2zh.utils.files import run_log_heartbeat


def test_run_log_heartbeat_appends_periodic_entries(tmp_path: Path) -> None:
    run_log = tmp_path / "run.log"

    with run_log_heartbeat(
        run_log,
        "translate",
        interval_seconds=0.01,
        context_provider=lambda: "current=3/10 page=2 unit_id=u00003",
    ):
        time.sleep(0.035)

    log_text = run_log.read_text(encoding="utf-8")
    assert "heartbeat phase=translate" in log_text
    assert "current=3/10 page=2 unit_id=u00003" in log_text
