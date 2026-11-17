from dataclasses import dataclass, field


@dataclass
class Cell:
    text: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False


@dataclass
class Table:
    title: str = ""
    rows: list[list[str]] = field(default_factory=list)
    source: str = ""
    bbox: tuple[int, int, int, int] | None = None
    confidence: float = 0.0

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "rows": self.rows,
            "source": self.source,
            "bbox": list(self.bbox) if self.bbox else None,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class FileResult:
    filename: str
    tables: list[Table] = field(default_factory=list)
    text: str = ""
    engine: str = ""
    error: str = ""
