import re
from html.parser import HTMLParser


class TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.spans: list[list[tuple[int, int]]] = []
        self._row: list[str] = []
        self._row_span: list[tuple[int, int]] = []
        self._cell: list[str] | None = None
        self._colspan = 1
        self._rowspan = 1

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._row = []
            self._row_span = []
        elif tag in ("td", "th"):
            self._cell = []
            attr = dict(attrs)
            try:
                self._colspan = max(1, int(attr.get("colspan", 1)))
            except (TypeError, ValueError):
                self._colspan = 1
            try:
                self._rowspan = max(1, int(attr.get("rowspan", 1)))
            except (TypeError, ValueError):
                self._rowspan = 1

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._row_span.append((self._colspan, self._rowspan))
            self._cell = None
        elif tag == "tr":
            if self._row:
                self.rows.append(list(self._row))
                self.spans.append(list(self._row_span))
            self._row = []
            self._row_span = []


def parse_table_html(html: str) -> tuple[list[list[str]], list[list[tuple[int, int]]]]:
    parser = TableHtmlParser()
    parser.feed(html or "")
    return parser.rows, parser.spans


def expand_spans(rows: list[list[str]], spans: list[list[tuple[int, int]]]) -> list[list[str]]:
    if not rows:
        return []
    width = sum(span[0] for span in spans[0]) if spans else len(rows[0])
    grid = [["" for _ in range(width)] for _ in range(len(rows))]
    for r, row in enumerate(rows):
        col = 0
        for c, (colspan, rowspan) in enumerate(spans[r] if r < len(spans) else []):
            value = row[c] if c < len(row) else ""
            for dr in range(rowspan):
                for dc in range(colspan):
                    rr, cc = r + dr, col + dc
                    if rr < len(grid) and cc < width:
                        grid[rr][cc] = value
            col += colspan
    return grid


def html_to_grid(html: str) -> list[list[str]]:
    rows, spans = parse_table_html(html)
    return expand_spans(rows, spans)


def is_title_row(row: list[str], spans: list[tuple[int, int]]) -> bool:
    filled = [c for c in row if c.strip()]
    if len(filled) != 1:
        return False
    return bool(spans) and spans[0][0] > 1
