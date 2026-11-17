import io
import re
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .models import FileResult, Table

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=12, color="1F4E78")
BODY_FONT = Font(size=11)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

INT_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*$|^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*\.\d+$|^[+-]?\d*\.\d+$")
PERCENT_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?%$")
CURRENCY_RE = re.compile(r"^([$€£¥￥])\s?([+-]?[\d,]*\.?\d+)$")
DATE_PATTERNS = [
    (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", "%Y-%m-%d"),
    (r"^(\d{4})/(\d{1,2})/(\d{1,2})$", "%Y/%m/%d"),
    (r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", "%Y-%m-%d"),
    (r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(:\d{2})?$", "%Y-%m-%d %H:%M:%S"),
]

CURRENCY_FORMATS = {"$": '"$"#,##0.00', "€": '"€"#,##0.00', "£": '"£"#,##0.00', "¥": '"¥"#,##0.00', "￥": '"¥"#,##0.00'}


def parse_number(text: str):
    match = PERCENT_RE.match(text)
    if match:
        value = float(match.group(0)[:-1]) / 100
        return value, "0.00%"
    if INT_RE.match(text):
        value = int(text.replace(",", ""))
        return value, None
    if FLOAT_RE.match(text):
        value = float(text.replace(",", ""))
        return value, None
    match = CURRENCY_RE.match(text)
    if match:
        symbol, digits = match.group(1), match.group(2)
        value = float(digits.replace(",", "")) if "." in digits else int(digits.replace(",", ""))
        return value, CURRENCY_FORMATS.get(symbol, None)
    return None, None


def parse_date(text: str):
    for pattern, _fmt in DATE_PATTERNS:
        match = re.match(pattern, text)
        if not match:
            continue
        parts = [int(g) for g in match.groups() if g is not None]
        try:
            if len(parts) == 3:
                return date(parts[0], parts[1], parts[2])
            if len(parts) >= 5:
                return datetime(*parts[:6])
        except ValueError:
            return None
    return None


def convert_cell(text: str):
    raw = str(text or "").strip()
    if not raw:
        return "", None
    if raw.startswith("="):
        return raw, None
    number, number_format = parse_number(raw)
    if number is not None:
        return number, number_format
    parsed_date = parse_date(raw)
    if parsed_date is not None:
        return parsed_date, None
    return raw, None


def safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]\:\*\?\/\\]", "_", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    index = 2
    while candidate.lower() in used:
        suffix = f"~{index}"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        index += 1
    used.add(candidate.lower())
    return candidate


def looks_like_header(row: list[str]) -> bool:
    if not row:
        return False
    filled = [c for c in row if c.strip()]
    if not filled:
        return False
    numeric = sum(1 for c in filled if parse_number(c.strip())[0] is not None)
    return numeric == 0


def write_table(sheet: Worksheet, table: Table, start_row: int, options: dict) -> int:
    row_cursor = start_row
    if table.title and options.get("include_titles", True):
        cell = sheet.cell(row=row_cursor, column=1, value=table.title)
        cell.font = TITLE_FONT
        row_cursor += 1
    if not table.rows:
        return row_cursor + 1
    header_row = bool(options.get("header", True))
    first_data_row = row_cursor
    for row_index, row in enumerate(table.rows):
        for col_index, value in enumerate(row):
            converted, number_format = convert_cell(value)
            cell = sheet.cell(row=row_cursor, column=col_index + 1, value=converted)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=False)
            if number_format:
                cell.number_format = number_format
            if isinstance(converted, (date, datetime)):
                cell.number_format = cell.number_format if number_format else "yyyy-mm-dd"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif isinstance(converted, (int, float)):
                cell.alignment = Alignment(horizontal="right", vertical="center")
        if header_row and row_index == 0:
            for col_index in range(len(row)):
                cell = sheet.cell(row=row_cursor, column=col_index + 1)
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        row_cursor += 1
    last_data_row = row_cursor - 1
    if header_row and last_data_row > first_data_row:
        sheet.freeze_panes = sheet.cell(row=first_data_row + 1, column=1)
        sheet.auto_filter.ref = (
            f"A{first_data_row}:{get_column_letter(max(len(table.rows[0]), 1))}{last_data_row}"
        )
    return last_data_row + 2


def autosize(sheet: Worksheet, max_width: int = 48) -> None:
    widths: dict[int, int] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            text = str(cell.value)
            length = 0
            for ch in text:
                length += 2 if ord(ch) > 127 else 1
            widths[cell.column] = max(widths.get(cell.column, 0), length)
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = min(width + 4, max_width)


def build_workbook(results: list[FileResult], options: dict | None = None) -> bytes:
    options = options or {}
    workbook = Workbook()
    index_sheet = workbook.active
    index_sheet.title = "目录"
    used_names: set[str] = {"目录"}
    index_sheet.append(["源文件", "表名", "行数", "列数", "所在工作表", "备注"])
    for cell in index_sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")

    merged = bool(options.get("merge_all"))
    merged_sheet = None
    if merged:
        merged_sheet = workbook.create_sheet("全部表格")
    for file_index, result in enumerate(results, start=1):
        if result.error and not result.tables:
            continue
        tables = result.tables
        if not tables and result.text:
            tables = [Table(title=f"{result.filename}（纯文本）", rows=[[result.text]])]
        if not tables:
            continue
        for table_index, table in enumerate(tables, start=1):
            if merged:
                sheet = merged_sheet
                row_cursor = sheet.max_row + 2 if sheet.max_row > 1 else 1
            else:
                base = f"图{file_index}-表{table_index}"
                if table.title:
                    base = f"图{file_index}-{table.title}"
                sheet_name = safe_sheet_name(base, used_names)
                sheet = workbook.create_sheet(sheet_name)
                row_cursor = 1
            if options.get("include_source", True):
                label = sheet.cell(row=row_cursor, column=1, value=f"来源: {result.filename}")
                label.font = Font(size=9, color="808080")
                row_cursor += 1
            end_row = write_table(sheet, table, row_cursor, options)
            index_sheet.append(
                [
                    result.filename,
                    table.title or f"表{table_index}",
                    table.n_rows,
                    table.n_cols,
                    sheet.title,
                    result.error or "",
                ]
            )

    for row in index_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    autosize(index_sheet, max_width=40)

    for sheet in workbook.worksheets:
        if sheet.title == "目录":
            continue
        autosize(sheet)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
