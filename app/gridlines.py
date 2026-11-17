import numpy as np


def _cluster_positions(values: list[int], gap: int = 6) -> list[int]:
    if not values:
        return []
    values = sorted(values)
    groups = [[values[0]]]
    for value in values[1:]:
        if value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(sum(group) / len(group))) for group in groups]


def _line_positions(mask: np.ndarray, axis: int, minimum_ratio: float) -> list[int]:
    counts = mask.sum(axis=axis)
    if counts.size == 0:
        return []
    peak = int(counts.max())
    if peak < 8:
        return []
    threshold = max(6, int(peak * minimum_ratio))
    hits = np.where(counts >= threshold)[0]
    return _cluster_positions([int(v) for v in hits])


def detect_grid_lines(image, bbox, min_lines: int = 3, upscale: float = 2.0):
    import cv2

    if image is None:
        return [], []
    scale = 1.0
    work = image
    if upscale and upscale > 1:
        scale = upscale
        work = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    height, width = work.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    margin = 12
    x1 = int(max(0, min(x1 * scale - margin, width)))
    x2 = int(max(0, min(x2 * scale + margin, width)))
    y1 = int(max(0, min(y1 * scale - margin, height)))
    y2 = int(max(0, min(y2 * scale + margin, height)))
    region = work[y1:y2, x1:x2]
    if region.size == 0:
        return [], []
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if region.ndim == 3 else region
    blurred = cv2.medianBlur(gray, 3)
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8
    )
    rows, cols = region.shape[:2]
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, rows // 12)))
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, cols // 12), 1))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    xs = _line_positions(vertical, axis=0, minimum_ratio=0.4)
    ys = _line_positions(horizontal, axis=1, minimum_ratio=0.4)
    if len(xs) < min_lines or len(ys) < min_lines:
        return [], []
    return [(x1 + x) / scale for x in xs], [(y1 + y) / scale for y in ys]


def build_cell_grid(items, xs: list[int], ys: list[int]) -> list[list[str]]:
    if not xs or not ys:
        return []
    columns = []
    for index in range(len(xs) - 1):
        left, right = xs[index], xs[index + 1]
        if right - left >= 3:
            columns.append((left, right))
    rows = []
    for index in range(len(ys) - 1):
        top, bottom = ys[index], ys[index + 1]
        if bottom - top >= 3:
            rows.append((top, bottom))
    if not columns or not rows:
        return []
    cells: dict[tuple[int, int], list[str]] = {}
    for item in items:
        column = _bucket(item.cx, columns)
        row = _bucket(item.cy, rows)
        if column is None or row is None:
            continue
        cells.setdefault((row, column), []).append(item.text)
    grid = []
    for row_index in range(len(rows)):
        line = []
        for column_index in range(len(columns)):
            parts = cells.get((row_index, column_index), [])
            line.append(" ".join(parts).strip())
        grid.append(line)
    return [row for row in grid if any(cell.strip() for cell in row)]


def _bucket(value: float, spans: list[tuple[int, int]]) -> int | None:
    if not spans:
        return None
    if value < spans[0][0] - 2:
        return 0
    for index, (left, right) in enumerate(spans):
        if left - 2 <= value <= right + 2:
            return index
    if value > spans[-1][1]:
        return len(spans) - 1
    return 0
