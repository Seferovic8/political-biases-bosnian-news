"""
Django settings for the Stav / article-stance analysis application.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-key-change-me-in-production-0123456789abcdef",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["*"]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "predictor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# No database is required for this application.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Sarajevo"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Machine-learning model configuration
# ---------------------------------------------------------------------------
# Root directory that holds the trained model artefacts. It is expected to
# contain the same sources referenced in the evaluation notebook:
#
#   <MODELS_ROOT>/models2               -> LogReg binary  (*.joblib)
#   <MODELS_ROOT>/models_stance         -> LogReg stance  (*.joblib)
#   <MODELS_ROOT>/bertic_models         -> BERTic binary  (HF dirs)
#   <MODELS_ROOT>/bertic_stance_models  -> BERTic stance  (HF dirs)
#
# The individual paths can be overridden with the *_SOURCE env vars below.
# When the artefacts are absent the app runs in a clearly-labelled DEMO mode
# using a deterministic keyword predictor, so the interface is fully usable
# without the (multi-GB) model files.
MODELS_ROOT = Path(os.environ.get("MODELS_ROOT", BASE_DIR / "models"))
print(MODELS_ROOT)
ML_CONFIG = {
    "MODELS_ROOT": MODELS_ROOT,
    "LOGREG_BINARY_SOURCE": Path(
        os.environ.get("LOGREG_BINARY_SOURCE", MODELS_ROOT / "models2")
    ),
    "LOGREG_STANCE_SOURCE": Path(
        os.environ.get("LOGREG_STANCE_SOURCE", MODELS_ROOT / "models_stance")
    ),
    "BERT_BINARY_SOURCE": Path(
        os.environ.get("BERT_BINARY_SOURCE", MODELS_ROOT / "bertic_models")
    ),
    "BERT_STANCE_SOURCE": Path(
        os.environ.get("BERT_STANCE_SOURCE", MODELS_ROOT / "bertic_stance_models")
    ),
    "LOGREG_WEIGHT": float(os.environ.get("LOGREG_WEIGHT", "0.5")),
    "BERT_WEIGHT": float(os.environ.get("BERT_WEIGHT", "0.5")),
    "BERT_BATCH_SIZE": int(os.environ.get("BERT_BATCH_SIZE", "16")),
    "MAX_LENGTH": int(os.environ.get("MAX_LENGTH", "512")),
    # Force demo mode even if model files happen to be present.
    "FORCE_DEMO": os.environ.get("FORCE_DEMO", "0") == "1",
}

# Networking guard for the scrapers (seconds).
SCRAPE_TIMEOUT = int(os.environ.get("SCRAPE_TIMEOUT", "30"))
