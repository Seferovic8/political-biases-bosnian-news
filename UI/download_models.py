import os
import zipfile
from pathlib import Path
import gdown

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
ZIP_PATH = BASE_DIR / "models.zip"

FILE_ID = "1OGPw3XuNljW_GXRrXxbpl4kDWEKNWzqw"

if not FILE_ID:
    print("GOOGLE_DRIVE_MODELS_ID nije postavljen, preskačem download.")
    exit(0)

if (MODELS_DIR / "models2").exists():
    print("Modeli već postoje, preskačem download.")
    exit(0)

url = f"https://drive.google.com/uc?id={FILE_ID}"

print("Skidam modele sa Google Drivea...")
gdown.download(url, str(ZIP_PATH), quiet=False)

print("Raspakujem modele...")
with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
    zip_ref.extractall(BASE_DIR)

ZIP_PATH.unlink(missing_ok=True)

print("Modeli skinuti i raspakovani.")