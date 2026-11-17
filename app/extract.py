from pathlib import Path

from .models import FileResult


def paddle_available() -> bool:
    from .paddle_engine import paddle_available as available

    return available()


def engines() -> list[dict]:
    return [
        {
            "id": "paddle",
            "name": "PaddleOCR 表格识别",
            "available": paddle_available(),
            "detail": "PP-StructureV3 版面分析 + 表格结构识别，中英文表格准确率最高",
        }
    ]


def extract_file(path: Path, engine: str = "paddle") -> FileResult:
    """只使用 PaddleOCR 识别表格；engine 仅为兼容旧调用保留，非 paddle 一律按 paddle 处理。"""
    result = FileResult(filename=path.name, engine="paddle")
    try:
        if not paddle_available():
            result.error = "PaddleOCR 不可用，请检查 paddlex / paddleocr 是否安装"
            return result
        from .paddle_engine import extract_tables

        tables, text = extract_tables(path)
        result.tables = tables
        result.text = text
        if not tables:
            result.error = "PaddleOCR 未识别到表格"
    except Exception as exc:
        result.error = str(exc)
    return result
