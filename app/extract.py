import base64
import io
import json
import re
import shutil
import tempfile
from pathlib import Path

from .config import (
    OCR_LANG,
    OCR_THREADS,
    VISION_API_KEY,
    VISION_BASE_URL,
    VISION_MODEL,
    VISION_TIMEOUT,
)
from .models import FileResult, Table

try:
    import pytesseract
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover
    pytesseract = None
    PILImage = None

try:
    from img2table.document import Image as DocumentImage
    from img2table.ocr import TesseractOCR
except ImportError:  # pragma: no cover
    DocumentImage = None
    TesseractOCR = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None

VISION_PROMPT = (
    "You transcribe every table visible in this image into structured data. "
    "Reply with JSON only, no prose, no markdown fence: "
    '{"tables":[{"title":"optional caption or empty string","rows":[["cell","cell"]]}]}. '
    "Rules: keep the original language and exact cell text, never translate or summarise; "
    "keep empty cells as empty strings; keep the row and column alignment of each table; "
    "return every distinct table you can read, in top-to-bottom order."
)


def clean_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _pad_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(r) for r in rows), default=0)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def _trim_blank_edges(rows: list[list[str]]) -> list[list[str]]:
    rows = [r for r in rows if any(clean_text(c) for c in r)]
    if not rows:
        return []
    width = len(rows[0])
    keep = [c for c in range(width) if any(clean_text(r[c]) for r in rows)]
    if not keep:
        return []
    first, last = keep[0], keep[-1]
    return [[r[c] for c in range(first, last + 1)] for r in rows]


class CellReader:
    def __init__(self) -> None:
        self._cache: dict[tuple, str] = {}

    def read(self, image, bbox) -> str:
        key = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        if key in self._cache:
            return self._cache[key]
        text = self._read(image, bbox)
        self._cache[key] = text
        return text

    def _read(self, image, bbox) -> str:
        if cv2 is None or image is None or pytesseract is None:
            return ""
        x1, y1, x2, y2 = (int(v) for v in bbox)
        height, width = image.shape[:2]
        x1 = max(0, min(x1, width))
        x2 = max(0, min(x2, width))
        y1 = max(0, min(y1, height))
        y2 = max(0, min(y2, height))
        cell_w, cell_h = x2 - x1, y2 - y1
        if cell_w < 6 or cell_h < 6:
            return ""
        inset = int(min(7, max(2, min(cell_w, cell_h) // 14)))
        crop = image[y1 + inset : y2 - inset, x1 + inset : x2 - inset]
        if crop.size == 0:
            return ""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        gray = cv2.copyMakeBorder(gray, 14, 14, 14, 14, cv2.BORDER_CONSTANT, value=255)
        scale = 4 if max(gray.shape[:2]) < 70 else 3
        upscaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        binary = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        attempts = [
            (binary, OCR_LANG, "--psm 7"),
            (upscaled, OCR_LANG, "--psm 6"),
            (binary, OCR_LANG, "--psm 8"),
            (binary, "eng", "--psm 7"),
        ]
        for candidate, lang, config in attempts:
            try:
                text = clean_text(
                    pytesseract.image_to_string(candidate, lang=lang, config=config)
                )
            except Exception:
                continue
            text = self._strip_border_noise(text)
            if text:
                return text
        return ""

    def _strip_border_noise(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^[\[\(\|=_~`\s]+", "", cleaned)
        cleaned = re.sub(r"[\[\)\|=_~`\s]+$", "", cleaned)
        cleaned = re.sub(r"[\[\]]", "", cleaned)
        return cleaned.strip()


class LocalExtractor:
    name = "local"

    def extract(self, path: Path) -> tuple[list[Table], str]:
        image = self._load_image(path)
        tables = self._tables_via_img2table(path, image)
        if not tables:
            tables = self._tables_via_lines(path)
        for table in tables:
            table.source = path.name
        return tables, ""

    def _load_image(self, path: Path):
        if cv2 is None:
            return None
        try:
            return cv2.imread(str(path))
        except Exception:
            return None

    def _tables_via_img2table(self, path: Path, image) -> list[Table]:
        if DocumentImage is None or TesseractOCR is None:
            return []
        try:
            ocr = TesseractOCR(n_threads=OCR_THREADS, lang=OCR_LANG, psm=11)
            document = DocumentImage(str(path))
            found = document.extract_tables(
                ocr=ocr,
                implicit_rows=False,
                implicit_columns=False,
                borderless_tables=True,
                min_confidence=40,
            )
        except Exception:
            return []
        reader = CellReader()
        tables: list[Table] = []
        for raw in found:
            rows: list[list[str]] = []
            for row_index in sorted(raw.content.keys()):
                cells = raw.content[row_index]
                row_values: list[str] = []
                for cell in cells:
                    fallback = clean_text(getattr(cell, "value", "") or "")
                    text = reader.read(image, (cell.bbox.x1, cell.bbox.y1, cell.bbox.x2, cell.bbox.y2))
                    row_values.append(text or fallback)
                rows.append(row_values)
            rows = _trim_blank_edges(rows)
            if len(rows) < 2 or len(rows[0]) < 2:
                continue
            bbox = None
            try:
                bbox = (
                    int(raw.bbox.x1),
                    int(raw.bbox.y1),
                    int(raw.bbox.x2),
                    int(raw.bbox.y2),
                )
            except Exception:
                bbox = None
            title = clean_text(getattr(raw, "title", "") or "")
            tables.append(Table(title=title, rows=rows, bbox=bbox, confidence=0.9))
        return tables

    def _tables_via_lines(self, path: Path) -> list[Table]:
        if pytesseract is None or PILImage is None:
            return []
        try:
            image = PILImage.open(path)
            image = image.convert("L")
            data = pytesseract.image_to_data(
                image, lang=OCR_LANG, config="--psm 6", output_type=pytesseract.Output.DICT
            )
        except Exception:
            return []
        lines: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
        for i, word in enumerate(data.get("text", [])):
            word = clean_text(word)
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append((data["left"][i], word))
        buckets: dict[int, list[str]] = {}
        for key in sorted(lines, key=lambda k: (k[0], k[1], k[2])):
            words = sorted(lines[key])
            left = min(w[0] for w in words)
            text = " ".join(w[1] for w in words)
            row_index = self._row_bucket(buckets, left, text)
            buckets[row_index] = text
        rows = [[value] for _, value in sorted(buckets.items())]
        rows = _trim_blank_edges(rows)
        if len(rows) < 2:
            return []
        return [Table(title="", rows=rows, confidence=0.5)]

    def _row_bucket(self, buckets: dict[int, str], left: int, text: str) -> int:
        for index in sorted(buckets):
            if abs(index - left) <= 12:
                return index
        return left


class VisionExtractor:
    name = "vision"

    def __init__(self) -> None:
        self.api_key = VISION_API_KEY
        self.base_url = VISION_BASE_URL.rstrip("/")
        self.model = VISION_MODEL

    def available(self) -> bool:
        return bool(self.api_key) and requests is not None

    def extract(self, path: Path) -> tuple[list[Table], str]:
        if not self.available():
            return [], "视觉模型未配置 API Key"
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=VISION_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except Exception as exc:
            return [], f"视觉模型调用失败: {exc}"
        tables = self._parse(content)
        for table in tables:
            table.source = path.name
        return tables, ""

    def _parse(self, content: str) -> list[Table]:
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        text = str(content).strip()
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if match:
            text = match.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end == -1:
                return []
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        raw_tables = data.get("tables") if isinstance(data, dict) else data
        if not isinstance(raw_tables, list):
            return []
        tables: list[Table] = []
        for raw in raw_tables:
            if not isinstance(raw, dict):
                continue
            rows = raw.get("rows") or raw.get("data") or []
            cleaned: list[list[str]] = []
            for row in rows:
                if isinstance(row, list):
                    cleaned.append([clean_text(c) for c in row])
            cleaned = _trim_blank_edges(_pad_rows(cleaned))
            if len(cleaned) < 1:
                continue
            tables.append(
                Table(
                    title=clean_text(raw.get("title", "")),
                    rows=cleaned,
                    confidence=1.0,
                )
            )
        return tables


class PlainTextExtractor:
    name = "text"

    def extract(self, path: Path) -> tuple[list[Table], str]:
        if pytesseract is None or PILImage is None:
            return [], "未安装 OCR 依赖"
        try:
            image = PILImage.open(path).convert("L")
            text = pytesseract.image_to_string(image, lang=OCR_LANG)
        except Exception as exc:
            return [], f"OCR 失败: {exc}"
        lines = [clean_text(line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        return [], "\n".join(lines)


def tesseract_installed() -> bool:
    if pytesseract is None:
        return False
    return shutil.which("tesseract") is not None


def vision_available() -> bool:
    return bool(VISION_API_KEY) and requests is not None


def paddle_available() -> bool:
    from .paddle_engine import paddle_available as available

    return available()


def engines() -> list[dict]:
    result = [
        {
            "id": "paddle",
            "name": "PaddleOCR 表格识别",
            "available": paddle_available(),
            "detail": "PP-StructureV3 版面分析 + 表格结构识别，中英文表格准确率最高",
        },
        {
            "id": "local",
            "name": "本地表格识别",
            "available": tesseract_installed(),
            "detail": "OpenCV 表格检测 + Tesseract OCR，完全离线",
        },
        {
            "id": "vision",
            "name": "视觉大模型",
            "available": vision_available(),
            "detail": f"OpenAI 兼容接口，模型 {VISION_MODEL}",
        },
        {
            "id": "text",
            "name": "仅提取文字",
            "available": tesseract_installed(),
            "detail": "不做表格结构识别，按纯文本输出",
        },
    ]
    return result


def extract_file(path: Path, engine: str = "auto") -> FileResult:
    result = FileResult(filename=path.name, engine=engine)
    try:
        if engine in ("auto", "paddle") and paddle_available():
            from .paddle_engine import extract_tables

            tables, text = extract_tables(path)
            result.engine = "paddle"
            if tables:
                result.tables = tables
                result.text = text
                return result
            if engine == "paddle":
                result.error = "PaddleOCR 未识别到表格"
                result.text = text
                return result
        if engine in ("auto", "vision") and vision_available():
            tables, error = VisionExtractor().extract(path)
            result.engine = "vision"
            if tables:
                result.tables = tables
                return result
            if engine == "vision":
                result.error = error or "视觉模型未返回表格"
                return result
        if engine in ("auto", "local"):
            tables, _ = LocalExtractor().extract(path)
            result.engine = "local"
            if tables:
                result.tables = tables
                return result
        if engine in ("auto", "text"):
            _, text = PlainTextExtractor().extract(path)
            result.engine = "text"
            result.text = text
            if not result.tables and not text:
                result.error = "未识别到内容"
            return result
        result.error = "没有可用的识别引擎"
    except Exception as exc:
        result.error = str(exc)
    return result
