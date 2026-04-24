from pathlib import Path
import sys

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from openpdf2zh.model_assets import (  # noqa: E402
    default_model_root,
    materialize_quickmt_models,
)


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    target_root = default_model_root(REPO_ROOT)
    result = materialize_quickmt_models(target_root)

    print(f"quickmt models materialized in {result}")


if __name__ == "__main__":
    main()
