from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
import tempfile
import tarfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv

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


def build_repo_url(repo_url: str) -> str:
    token = os.getenv("OPENPDF2ZH_MODEL_REPO_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return repo_url
    if repo_url.startswith("https://github.com/"):
        prefix = "https://github.com/"
        remainder = repo_url[len(prefix) :]
        return f"https://x-access-token:{quote(token, safe='')}@github.com/{remainder}"
    return repo_url


def download_model_bundle(bundle_url: str, destination: Path) -> None:
    request = Request(bundle_url)
    token = os.getenv("OPENPDF2ZH_MODEL_REPO_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if "github.com" in bundle_url and "/releases/assets/" in bundle_url:
        request.add_header("Accept", "application/octet-stream")

    with urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def verify_sha256(path: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"Downloaded quickmt bundle SHA256 mismatch. Expected {expected_sha256}, got {actual}."
        )


def extract_model_bundle(archive_path: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(target_root)


def materialize_from_bundle(bundle_url: str, target_root: Path) -> None:
    expected_sha256 = os.getenv("OPENPDF2ZH_MODEL_BUNDLE_SHA256", "").strip()
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / "quickmt-models.tar.gz"
        download_model_bundle(bundle_url, archive_path)
        if expected_sha256:
            verify_sha256(archive_path, expected_sha256)
        extract_model_bundle(archive_path, target_root)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    target_root = Path(
        os.getenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR") or repo_root / "models"
    ).expanduser()

    if has_real_models(target_root):
        print(f"quickmt models already materialized in {target_root}")
        return

    bundle_url = os.getenv("OPENPDF2ZH_MODEL_BUNDLE_URL", "").strip()
    if bundle_url:
        materialize_from_bundle(bundle_url, target_root)
        if not has_real_models(target_root):
            raise RuntimeError(
                f"Downloaded quickmt bundle from {bundle_url}, but real model files were not materialized into {target_root}."
            )
        print(f"quickmt models materialized in {target_root}")
        return

    if not (os.getenv("OPENPDF2ZH_MODEL_REPO_TOKEN") or os.getenv("GITHUB_TOKEN")):
        raise RuntimeError(
            "No quickmt model source configured. Set OPENPDF2ZH_MODEL_BUNDLE_URL (preferred) or OPENPDF2ZH_MODEL_REPO_TOKEN/GITHUB_TOKEN before running the Railway build."
        )

    repo_url = os.getenv("OPENPDF2ZH_MODEL_REPO_URL", DEFAULT_REPO_URL)
    repo_ref = os.getenv("OPENPDF2ZH_MODEL_REPO_REF") or os.getenv(
        "RAILWAY_GIT_COMMIT_SHA",
        "main",
    )
    clone_url = build_repo_url(repo_url)

    with tempfile.TemporaryDirectory() as tmp_dir:
        clone_dir = Path(tmp_dir) / "repo"
        try:
            run("git", "clone", clone_url, str(clone_dir))
        except subprocess.CalledProcessError as exc:
            if clone_url == repo_url and repo_url.startswith("https://github.com/"):
                raise RuntimeError(
                    "Failed to clone the model repository during build. If the GitHub repository is private, "
                    "set OPENPDF2ZH_MODEL_REPO_TOKEN (or GITHUB_TOKEN) in Railway, or provide OPENPDF2ZH_MODEL_BUNDLE_URL so the build can fetch the real quickmt model files."
                ) from exc
            raise
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
