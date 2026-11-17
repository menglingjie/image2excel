import os
import queue
import threading
import time

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("OMP_NUM_THREADS", "2")

from .config import (
    PADDLE_ENABLED,
    PADDLE_LANG,
    PADDLE_LAYOUT_MODEL,
    PADDLE_MAX_CANDIDATES,
    PADDLE_OCR_DET,
    PADDLE_OCR_REC,
    PADDLE_REC_BATCH,
    PADDLE_TARGET_SIDE,
)
from .grid import TextItem, build_grid
from .gridlines import detect_grid_lines
from .models import Table
from .tables import html_to_grid

_PIPELINE = None
_PIPELINE_LOCK = threading.Lock()
_PIPELINE_FAILED = False
_QUEUE: "queue.Queue" = queue.Queue()
_WORKER: threading.Thread | None = None


def _worker_loop() -> None:
    while True:
        job = _QUEUE.get()
        if job is None:
            _QUEUE.task_done()
            break
        path, limit, slot = job
        try:
            slot["result"] = list(get_pipeline().predict(path, text_det_limit_side_len=limit))
        except Exception as exc:
            slot["error"] = exc
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    with _PIPELINE_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="paddle-worker", daemon=True)
            _WORKER.start()


def run_pipeline(path, limit):
    _ensure_worker()
    slot: dict = {}
    _QUEUE.put((str(path), limit, slot))
    while "result" not in slot and "error" not in slot:
        time.sleep(0.02)
    if "error" in slot:
        raise slot["error"]
    return slot["result"]


def paddle_available() -> bool:
    if not PADDLE_ENABLED:
        return False
    try:
        import paddleocr  # noqa: F401
    except Exception:
        return False
    return True


def _patch_run_mode() -> None:
    try:
        import paddlex.inference.models.runners.paddle_static.config.pp_option as pp_option
    except Exception:
        return
    pp_option.get_default_run_mode = _run_mode


def _run_mode(model_name, device_type):
    if device_type == "cpu" and model_name and model_name.endswith("_rec"):
        return "mkldnn"
    return "paddle"


def _build_pipeline():
    from paddleocr import PPStructureV3

    _patch_run_mode()
    return PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_seal_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        layout_detection_model_name=PADDLE_LAYOUT_MODEL,
        text_detection_model_name=PADDLE_OCR_DET,
        text_recognition_model_name=PADDLE_OCR_REC,
        text_det_limit_side_len=PADDLE_TARGET_SIDE,
        text_recognition_batch_size=PADDLE_REC_BATCH,
        layout_threshold=0.2,
    )


def prepare_image(path):
    import cv2

    return cv2.imread(str(path))


def detection_limit(path) -> int:
    from PIL import Image

    try:
        with Image.open(path) as image:
            long_side = max(image.size)
    except Exception:
        long_side = PADDLE_TARGET_SIDE
    if long_side <= PADDLE_TARGET_SIDE // 2:
        target = long_side * 2
    else:
        target = long_side
    return int(min(PADDLE_TARGET_SIDE, max(480, target)))


def get_pipeline():
    global _PIPELINE, _PIPELINE_FAILED
    if _PIPELINE is not None:
        return _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is None and not _PIPELINE_FAILED:
            try:
                _PIPELINE = _build_pipeline()
                _raise_detection_cap(_PIPELINE)
            except Exception:
                _PIPELINE_FAILED = True
                raise
    return _PIPELINE


def _raise_detection_cap(pipeline) -> None:
    models = []
    outer = getattr(pipeline, "paddlex_pipeline", None)
    inner = getattr(outer, "_pipeline", outer)
    ocr_pipeline = getattr(inner, "general_ocr_pipeline", None)
    ocr_inner = getattr(ocr_pipeline, "_pipeline", ocr_pipeline)
    detector = getattr(ocr_inner, "text_det_model", None)
    if detector is None:
        detector = getattr(inner, "text_det_model", None)
    if detector is None:
        return
    post_op = getattr(detector, "post_op", None)
    if post_op is not None and hasattr(post_op, "max_candidates"):
        post_op.max_candidates = PADDLE_MAX_CANDIDATES
        models.append(detector)
    for model in models:
        print(f"[image2excel] 检测框上限已提升到 {PADDLE_MAX_CANDIDATES}")


def _ocr_items(ocr_res: dict, bbox) -> list[TextItem]:
    import numpy as np

    x1, y1, x2, y2 = bbox
    items: list[TextItem] = []
    polys = ocr_res.get("dt_polys") or []
    texts = ocr_res.get("rec_texts") or []
    scores = ocr_res.get("rec_scores") or []
    for index, poly in enumerate(polys):
        if index >= len(texts):
            break
        text = (texts[index] or "").strip()
        if not text:
            continue
        points = np.array(poly)
        bx1, by1 = float(points[:, 0].min()), float(points[:, 1].min())
        bx2, by2 = float(points[:, 0].max()), float(points[:, 1].max())
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        if not (x1 - 6 <= cx <= x2 + 6 and y1 - 6 <= cy <= y2 + 6):
            continue
        score = scores[index] if index < len(scores) else 1.0
        if score < 0.15:
            continue
        items.append(TextItem(text, bx1, by1, bx2, by2))
    return items


def _title_for(blocks: list[dict], table_bbox) -> str:
    tx1, ty1, tx2, ty2 = table_bbox
    best = ""
    best_distance = None
    for block in blocks:
        if block.get("block_label") != "table_title":
            continue
        bx1, by1, bx2, by2 = block.get("block_bbox") or (0, 0, 0, 0)
        if bx2 < tx1 - 20 or bx1 > tx2 + 20:
            continue
        distance = ty1 - by2
        if distance < -10:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = str(block.get("block_content") or "").strip()
    return best


def extract_tables(path) -> tuple[list[Table], str]:
    tables: list[Table] = []
    texts: list[str] = []
    image = prepare_image(path)
    limit = detection_limit(path)
    results = run_pipeline(path, limit)
    for result in results:
        data = result.json.get("res", {})
        blocks = data.get("parsing_res_list", []) or []
        ocr_res = data.get("overall_ocr_res", {}) or {}
        for block in blocks:
            label = block.get("block_label")
            bbox = block.get("block_bbox")
            if label == "table" and bbox:
                table = _table_from_block(block, blocks, ocr_res, image)
                if table is not None:
                    tables.append(table)
            elif label in ("text", "table_title", "chart_title", "doc_title") and bbox:
                content = str(block.get("block_content") or "").strip()
                if content:
                    texts.append(content)
    return tables, "\n".join(texts)


def _table_from_block(
    block: dict, blocks: list[dict], ocr_res: dict, image=None
) -> Table | None:
    bbox = tuple(block.get("block_bbox"))
    html_rows = html_to_grid(str(block.get("block_content") or ""))
    items = _ocr_items(ocr_res, bbox)
    column_spans = _column_spans(image, bbox)
    grid = build_grid(items, column_spans=column_spans)
    title = _title_for(blocks, bbox)

    html_width = max((len(row) for row in html_rows), default=0)
    if html_rows and html_width > 1 and len([c for c in html_rows[0] if c.strip()]) == 1:
        title = title or html_rows[0][0]

    if grid:
        rows = grid
        if len(rows) > 1 and len([c for c in rows[0] if c.strip()]) == 1:
            title = title or rows[0][0].strip()
            rows = rows[1:]
    else:
        rows = html_rows

    if not rows:
        return None
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return None
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return Table(title=title, rows=rows, bbox=bbox, confidence=0.95)


def _column_spans(image, bbox) -> list[tuple[int, int]] | None:
    xs, _ys = detect_grid_lines(image, bbox)
    if len(xs) < 3:
        return None
    spans = []
    for index in range(len(xs) - 1):
        left, right = xs[index], xs[index + 1]
        if right - left >= 6:
            spans.append((left, right))
    if len(spans) < 2:
        return None
    return spans
