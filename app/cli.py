import argparse
import sys
from pathlib import Path

from .excel import build_workbook
from .extract import extract_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="image2excel", description="把图片里的表格转换成 Excel")
    parser.add_argument("images", nargs="+", help="图片文件路径")
    parser.add_argument("-o", "--output", default="output.xlsx", help="输出 xlsx 路径")
    parser.add_argument("-e", "--engine", default="paddle", choices=["paddle"], help="识别引擎（目前只有 PaddleOCR）")
    parser.add_argument("--merge-all", action="store_true", help="所有表格合并到一个工作表")
    parser.add_argument("--no-header", action="store_true", help="不把首行当表头")
    args = parser.parse_args(argv)

    paths = []
    for item in args.images:
        path = Path(item)
        if path.is_dir():
            paths.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}))
        else:
            paths.append(path)
    if not paths:
        print("没有找到图片", file=sys.stderr)
        return 1

    results = []
    for path in paths:
        result = extract_file(path, args.engine)
        results.append(result)
        status = "错误: " + result.error if result.error else f"{len(result.tables)} 个表格"
        print(f"{path.name}: {status}")

    data = build_workbook(
        results,
        {"merge_all": args.merge_all, "header": not args.no_header},
    )
    output = Path(args.output)
    output.write_bytes(data)
    print(f"已写入 {output} ({len(data)} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
