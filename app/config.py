import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("I2E_STORAGE_DIR", BASE_DIR / "storage"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_UPLOAD_MB = int(os.getenv("I2E_MAX_UPLOAD_MB", "20"))
MAX_FILES = int(os.getenv("I2E_MAX_FILES", "10"))
OCR_LANG = os.getenv("I2E_OCR_LANG", "chi_sim+eng")
OCR_THREADS = int(os.getenv("I2E_OCR_THREADS", "4"))

VISION_API_KEY = os.getenv("I2E_VISION_API_KEY", "")
VISION_BASE_URL = os.getenv("I2E_VISION_BASE_URL", "https://api.openai.com/v1")
VISION_MODEL = os.getenv("I2E_VISION_MODEL", "gpt-4o")
VISION_TIMEOUT = int(os.getenv("I2E_VISION_TIMEOUT", "120"))

PADDLE_ENABLED = os.getenv("I2E_PADDLE_ENABLED", "1") not in ("0", "false", "False")
PADDLE_LANG = os.getenv("I2E_PADDLE_LANG", "ch")
PADDLE_LAYOUT_MODEL = os.getenv("I2E_PADDLE_LAYOUT", "PP-DocLayout-L")
PADDLE_OCR_DET = os.getenv("I2E_PADDLE_DET", "PP-OCRv5_mobile_det")
PADDLE_OCR_REC = os.getenv("I2E_PADDLE_REC", "PP-OCRv5_server_rec")
PADDLE_MAX_CANDIDATES = int(os.getenv("I2E_PADDLE_MAX_CANDIDATES", "20000"))
PADDLE_TARGET_SIDE = int(os.getenv("I2E_PADDLE_TARGET_SIDE", "2560"))
PADDLE_REC_BATCH = int(os.getenv("I2E_PADDLE_REC_BATCH", "32"))

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
