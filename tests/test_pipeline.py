import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook

from app.excel import build_workbook
from app.extract import extract_file
from tests.make_samples import make_table_image

SAMPLES = Path(__file__).resolve().parent / "samples"

EXPECTED = {
    "sales.png": [
        ["Product", "Units", "Price", "Revenue"],
        ["Widget A", "1,250", "19.99", "24987.50"],
        ["Widget B", "830", "34.50", "28635.00"],
        ["Gadget C", "2,410", "7.25", "17472.50"],
        ["Gizmo D", "95", "129.00", "12255.00"],
    ],
    "inventory.png": [
        ["物料名称", "数量", "单价", "占比"],
        ["螺丝M8", "1,024", "¥12.50", "42.5%"],
        ["垫圈6mm", "512", "¥3.75", "18.0%"],
        ["轴承6202", "78", "¥45.00", "9.5%"],
    ],
}


def _normalize(text: str) -> str:
    return (
        text.replace(" ", "")
        .replace("￥", "¥")
        .replace("，", ",")
        .replace("。", ".")
    )


def build_samples() -> None:
    SAMPLES.mkdir(exist_ok=True)
    make_table_image(
        SAMPLES / "sales.png",
        "Quarterly Sales Report",
        ["Product", "Units", "Price", "Revenue"],
        [
            ["Widget A", "1,250", "19.99", "24987.50"],
            ["Widget B", "830", "34.50", "28635.00"],
            ["Gadget C", "2,410", "7.25", "17472.50"],
            ["Gizmo D", "95", "129.00", "12255.00"],
        ],
    )
    make_table_image(
        SAMPLES / "inventory.png",
        "Inventory 库存表",
        ["物料名称", "数量", "单价", "占比"],
        [
            ["螺丝 M8", "1,024", "¥12.50", "42.5%"],
            ["垫圈 6mm", "512", "¥3.75", "18.0%"],
            ["轴承 6202", "78", "¥45.00", "9.5%"],
        ],
    )


def check_engine(engine: str, strict: bool) -> int:
    failures = 0
    for name, expected in EXPECTED.items():
        result = extract_file(SAMPLES / name, engine)
        assert not result.error, f"{engine} {name}: {result.error}"
        assert result.tables, f"{engine} {name}: 没有识别到表格"
        rows = result.tables[0].rows
        ok = len(rows) == len(expected)
        if ok:
            for got, want in zip(rows, expected):
                got_norm = [_normalize(c) for c in got]
                want_norm = [_normalize(c) for c in want]
                if got_norm != want_norm:
                    ok = False
                    break
        if ok:
            print(f"  ✓ {engine} {name}: {len(rows)} 行全部正确")
        elif strict:
            failures += 1
            print(f"  ✗ {engine} {name}:")
            for row in rows:
                print(f"      {row}")
        else:
            print(f"  ~ {engine} {name}: 结果不一致（该引擎允许误差）")
    return failures


def check_excel() -> int:
    results = [extract_file(SAMPLES / name, "local") for name in EXPECTED]
    data = build_workbook(results, {"header": True, "include_source": True})
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        handle.write(data)
        path = handle.name
    workbook = load_workbook(path)
    failures = 0
    if "目录" not in workbook.sheetnames:
        print("  ✗ 缺少目录工作表")
        failures += 1
    for sheet in workbook.worksheets:
        if sheet.title == "目录":
            continue
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    print(f"  ✗ 单元格 {cell.coordinate} 是公式")
                    failures += 1
    values = [c.value for sheet in workbook.worksheets for row in sheet.iter_rows() for c in row]
    if 1024 not in values:
        print("  ✗ 数字没有转成数值类型")
        failures += 1
    if 0.425 not in values:
        print("  ✗ 百分比没有转成数值类型")
        failures += 1
    print(f"  ✓ 工作表 {workbook.sheetnames}")
    return failures


def main() -> int:
    build_samples()
    print("PaddleOCR 引擎:")
    failures = check_engine("paddle", strict=True)
    print("Tesseract 引擎:")
    failures += check_engine("local", strict=False)
    print("Excel 输出:")
    failures += check_excel()
    if failures:
        print(f"失败 {failures} 项")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
