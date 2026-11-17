import re
from statistics import median

NUMERIC_RE = re.compile(r"^[+\-−(]?\s*[$€£¥￥]?\s*\d[\d,]*(\.\d+)?\s*%?\)?$")


def looks_numeric(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False
    return bool(NUMERIC_RE.match(value))


class TextItem:
    __slots__ = ("text", "cx", "cy", "x1", "x2", "y1", "y2")

    def __init__(self, text: str, x1: float, y1: float, x2: float, y2: float) -> None:
        self.text = text
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.cx = (x1 + x2) / 2
        self.cy = (y1 + y2) / 2


def cluster_rows(items: list[TextItem], tolerance: float | None = None) -> list[list[TextItem]]:
    if not items:
        return []
    heights = [max(1.0, it.y2 - it.y1) for it in items]
    if tolerance is None:
        tolerance = max(6.0, median(heights) * 0.55)
    ordered = sorted(items, key=lambda it: (it.cy, it.cx))
    rows: list[list[TextItem]] = []
    current: list[TextItem] = []
    anchor = 0.0
    for item in ordered:
        if current and abs(item.cy - anchor) <= tolerance:
            current.append(item)
            anchor = sum(it.cy for it in current) / len(current)
        else:
            if current:
                rows.append(current)
            current = [item]
            anchor = item.cy
    if current:
        rows.append(current)
    return [sorted(row, key=lambda it: it.cx) for row in rows]


def _reference_centers(rows: list[list[TextItem]], columns: int) -> list[float]:
    full = [row for row in rows if len(row) == columns]
    if not full:
        full = [max(rows, key=len)]
    centers: list[list[float]] = [[] for _ in range(columns)]
    for row in full:
        for index, item in enumerate(row[:columns]):
            centers[index].append(item.cx)
    return [median(values) if values else 0.0 for values in centers]


def _assign(items: list[TextItem], centers: list[float]) -> list[int]:
    pairs = []
    for item_index, item in enumerate(items):
        for col_index, center in enumerate(centers):
            pairs.append((abs(item.cx - center), item_index, col_index))
    pairs.sort()
    assignment = [-1] * len(items)
    used_cols: set[int] = set()
    for _dist, item_index, col_index in pairs:
        if assignment[item_index] == -1 and col_index not in used_cols:
            assignment[item_index] = col_index
            used_cols.add(col_index)
    for item_index, col_index in enumerate(assignment):
        if col_index == -1:
            best = min(range(len(centers)), key=lambda c: abs(items[item_index].cx - centers[c]))
            assignment[item_index] = best
    return assignment


def _merge_extra(row: list[TextItem], columns: int) -> list[str]:
    if len(row) <= columns:
        return [item.text for item in row]
    groups: list[list[TextItem]] = [[row[0]]]
    typical = _typical_gap(row)
    for index in range(1, len(row)):
        gap = row[index].cx - row[index - 1].cx
        if len(groups) < columns and gap > typical * 1.5:
            groups.append([row[index]])
        else:
            groups[-1].append(row[index])
    return [" ".join(item.text for item in group).strip() for group in groups][:columns]


def _typical_gap(row: list[TextItem]) -> float:
    if len(row) < 2:
        return 0.0
    gaps = sorted(row[i + 1].cx - row[i].cx for i in range(len(row) - 1))
    return gaps[len(gaps) // 2]


def _row_is_numeric(row: list[str]) -> bool:
    filled = [c for c in row if c.strip()]
    if not filled:
        return False
    numeric = sum(1 for c in filled if looks_numeric(c))
    return numeric >= max(1, len(filled) * 0.5)


def _merge_header(grid: list[list[str]], row_groups: list[list[TextItem]]) -> list[list[str]]:
    if len(grid) < 3:
        return grid
    data_index = None
    for index, row in enumerate(grid):
        if _row_is_numeric(row):
            data_index = index
            break
    if data_index is None or data_index < 2:
        return grid
    row_ys = [median([it.cy for it in group]) for group in row_groups]
    gaps = [row_ys[i + 1] - row_ys[i] for i in range(len(row_ys) - 1)]
    spacing = median(gaps) if gaps else 0.0
    if spacing <= 0:
        return grid
    for index in range(1, data_index):
        if row_ys[index] - row_ys[index - 1] > spacing * 1.8:
            return grid
    merged = []
    for column in range(len(grid[0])):
        parts = []
        for index in range(data_index):
            value = grid[index][column].strip()
            if value:
                parts.append(value)
        merged.append(" ".join(parts))
    return [merged] + grid[data_index:]


def build_grid(
    items: list[TextItem],
    merge_header: bool = True,
    column_spans: list[tuple[int, int]] | None = None,
) -> list[list[str]]:
    row_groups = cluster_rows(items)
    if not row_groups:
        return []
    if column_spans:
        grid = _grid_from_spans(row_groups, column_spans)
    else:
        grid = _grid_from_clusters(row_groups)
    if merge_header:
        grid = _merge_header(grid, row_groups)
    grid = [row for row in grid if any(cell.strip() for cell in row)]
    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def _grid_from_spans(
    row_groups: list[list[TextItem]], column_spans: list[tuple[int, int]]
) -> list[list[str]]:
    grid = [["" for _ in column_spans] for _ in row_groups]
    for row_index, row in enumerate(row_groups):
        for item in row:
            column = _bucket(item.cx, column_spans)
            if column is None:
                continue
            current = grid[row_index][column]
            grid[row_index][column] = f"{current} {item.text}".strip() if current else item.text
    return grid


def _bucket(value: float, spans: list[tuple[int, int]]) -> int | None:
    if not spans:
        return None
    for index, (left, right) in enumerate(spans):
        if left - 4 <= value <= right + 4:
            return index
    if value < spans[0][0]:
        return 0
    return len(spans) - 1


def _grid_from_clusters(row_groups: list[list[TextItem]]) -> list[list[str]]:
    columns = max(len(row) for row in row_groups)
    if columns == 0:
        return []
    centers = _reference_centers(row_groups, columns)
    grid: list[list[str]] = []
    for row in row_groups:
        cells = [""] * columns
        if len(row) == columns:
            for index, item in enumerate(row):
                cells[index] = item.text
        elif len(row) > columns:
            for index, text in enumerate(_merge_extra(row, columns)):
                cells[index] = text
        else:
            for index, col_index in enumerate(_assign(row, centers)):
                cells[col_index] = row[index].text
        grid.append(cells)
    return grid
