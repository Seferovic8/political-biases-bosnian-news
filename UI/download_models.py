import os
import sys
import zipfile
from pathlib import Path

import gdown

BASE_DIR = Path(__file__).resolve().parent

MODELS_DIR = Path(
    os.environ.get(
        "MODELS_ROOT",
        os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", BASE_DIR / "models"),
    )
)

ZIP_PATH = MODELS_DIR / "models.zip"
FILE_ID = "1QZ_zQQXb6HlHSyyHejIuPzgYaGBgR8OM"

required_dirs = [
    MODELS_DIR / "models2",
    MODELS_DIR / "models_stance",
    MODELS_DIR / "bertic_models",
    MODELS_DIR / "bertic_stance_models",
]

MODELS_DIR.mkdir(parents=True, exist_ok=True)

if all(path.exists() for path in required_dirs):
    print(f"Svi modeli već postoje u {MODELS_DIR}.")
    sys.exit(0)

url = f"https://drive.google.com/uc?id={FILE_ID}"

print(f"Skidam modele u {ZIP_PATH}...")
result = gdown.download(url, str(ZIP_PATH), quiet=False)

if not result or not ZIP_PATH.exists():
    raise RuntimeError("Preuzimanje models.zip nije uspjelo.")

print(f"Raspakujem modele u {MODELS_DIR}...")

with zipfile.ZipFile(ZIP_PATH, "r") as archive:
    archive.extractall(MODELS_DIR)

ZIP_PATH.unlink(missing_ok=True)

missing = [str(path) for path in required_dirs if not path.exists()]

if missing:
    raise RuntimeError(
        "Nakon raspakivanja nedostaju folderi: " + ", ".join(missing)
    )

print("Modeli su uspješno spremljeni u persistent volume.")