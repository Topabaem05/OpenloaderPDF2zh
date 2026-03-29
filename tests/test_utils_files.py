import os
import time
from pathlib import Path

from openpdf2zh.utils.files import cleanup_expired_workspaces, run_log_heartbeat


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


def test_cleanup_expired_workspaces_removes_old_workspace_only(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    old_workspace = workspace_root / "old-job"
    fresh_workspace = workspace_root / "fresh-job"
    old_workspace.mkdir(parents=True)
    fresh_workspace.mkdir(parents=True)
    (old_workspace / "artifact.txt").write_text("old", encoding="utf-8")
    (fresh_workspace / "artifact.txt").write_text("fresh", encoding="utf-8")

    now = time.time()
    old_mtime = now - 7200
    fresh_mtime = now - 60
    for path in [old_workspace, old_workspace / "artifact.txt"]:
        os.utime(path, (old_mtime, old_mtime))
    for path in [fresh_workspace, fresh_workspace / "artifact.txt"]:
        os.utime(path, (fresh_mtime, fresh_mtime))

    deleted = cleanup_expired_workspaces(workspace_root, retention_seconds=3600)

    assert deleted == [old_workspace]
    assert not old_workspace.exists()
    assert fresh_workspace.exists()
