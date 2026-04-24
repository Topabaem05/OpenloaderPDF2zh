from __future__ import annotations

import os
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_DIRS = ("quickmt-ko-en", "quickmt-en-ko")
DEFAULT_HF_MODELS = {
    "quickmt-ko-en": {
        "repo_id": "quickmt/quickmt-ko-en",
        "revision": "33b35a7afa91037ccf8c607c9e6e26e3e10ddcdd",
    },
    "quickmt-en-ko": {
        "repo_id": "quickmt/quickmt-en-ko",
        "revision": "08e130e4f742c4442377983c66294d57bebe0cc7",
    },
}
MODEL_FILES = (
    "config.json",
    "model.bin",
    "source_vocabulary.json",
    "src.spm.model",
    "target_vocabulary.json",
    "tgt.spm.model",
)


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


def materialize_from_hugging_face(target_root: Path) -> None:
    token = os.getenv("OPENPDF2ZH_QUICKMT_HF_TOKEN") or os.getenv("HF_TOKEN")
    target_root.mkdir(parents=True, exist_ok=True)

    for model_dir, defaults in DEFAULT_HF_MODELS.items():
        repo_id = os.getenv(
            f"OPENPDF2ZH_{model_dir.upper().replace('-', '_')}_HF_REPO_ID",
            defaults["repo_id"],
        ).strip()
        revision = os.getenv(
            f"OPENPDF2ZH_{model_dir.upper().replace('-', '_')}_HF_REVISION",
            defaults["revision"],
        ).strip()
        local_dir = target_root / model_dir
        if local_dir.exists():
            shutil.rmtree(local_dir)
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            token=token,
            local_dir=str(local_dir),
            allow_patterns=list(MODEL_FILES),
        )


def default_model_root(repo_root: Path) -> Path:
    return Path(
        os.getenv("OPENPDF2ZH_CTRANSLATE2_MODEL_DIR")
        or repo_root / "resources" / "models" / "quickmt"
    ).expanduser().resolve()


def materialize_quickmt_models(target_root: Path) -> Path:
    target_root = target_root.expanduser().resolve()

    if has_real_models(target_root):
        return target_root

    materialize_from_hugging_face(target_root)

    if not has_real_models(target_root):
        raise RuntimeError(
            f"Failed to materialize quickmt models into {target_root} from Hugging Face. "
            "Check the configured Hugging Face repo IDs, revisions, and HF token if the model repository is private or gated."
        )
    return target_root
