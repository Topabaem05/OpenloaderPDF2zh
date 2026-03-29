from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MODEL_DIRS = ("quickmt-ko-en", "quickmt-en-ko")
DEFAULT_REPO_URL = "https://github.com/Topabaem05/OpenloaderPDF2zh.git"


def is_lfs_pointer(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.readline().startswith(
            b"version https://git-lfs.github.com/spec/v1"
        )


def has_real_models(root: Path) -> bool:
    return all(
        (root / model_dir / "model.bin").is_file()
        and not is_lfs_pointer(root / model_dir / "model.bin")
        and (root / model_dir / "model.bin").stat().st_size > 1_000_000
        and (root / model_dir / "src.spm.model").is_file()
        and (root / model_dir / "tgt.spm.model").is_file()
        for model_dir in MODEL_DIRS
    )


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=str(cwd) if cwd else None, check=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    target_root = Path(
        os.getenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR") or repo_root / "models"
    ).expanduser()

    if has_real_models(target_root):
        print(f"quickmt models already materialized in {target_root}")
        return

    repo_url = os.getenv("OPENPDF2ZH_MODEL_REPO_URL", DEFAULT_REPO_URL)
    repo_ref = os.getenv("OPENPDF2ZH_MODEL_REPO_REF") or os.getenv(
        "RAILWAY_GIT_COMMIT_SHA",
        "main",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        clone_dir = Path(tmp_dir) / "repo"
        run("git", "clone", repo_url, str(clone_dir))
        run("git", "checkout", repo_ref, cwd=clone_dir)
        run("git", "lfs", "install", "--local", cwd=clone_dir)
        run(
            "git",
            "lfs",
            "pull",
            "--include",
            "models/quickmt-ko-en/**,models/quickmt-en-ko/**",
            cwd=clone_dir,
        )

        source_root = clone_dir / "models"
        target_root.mkdir(parents=True, exist_ok=True)
        for model_dir in MODEL_DIRS:
            source_dir = source_root / model_dir
            if not source_dir.is_dir():
                raise RuntimeError(f"Missing model directory in clone: {source_dir}")
            destination_dir = target_root / model_dir
            if destination_dir.exists():
                shutil.rmtree(destination_dir)
            shutil.copytree(source_dir, destination_dir)

    if not has_real_models(target_root):
        raise RuntimeError(
            f"Failed to materialize quickmt models into {target_root}. "
            "The copied model files are still missing or are Git LFS pointers."
        )

    print(f"quickmt models materialized in {target_root}")


if __name__ == "__main__":
    main()
