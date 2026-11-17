import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def load_font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_table_image(path: Path, title: str, headers: list[str], rows: list[list[str]]) -> Path:
    font = load_font(22)
    title_font = load_font(30)
    col_widths = []
    for index in range(len(headers)):
        longest = max([len(headers[index])] + [len(r[index]) for r in rows])
        col_widths.append(max(110, longest * 16 + 30))
    row_height = 44
    margin = 30
    title_height = 56
    width = margin * 2 + sum(col_widths)
    height = margin * 2 + title_height + row_height * (len(rows) + 1)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((margin, margin), title, fill="black", font=title_font)

    top = margin + title_height
    left = margin
    x = left
    for index, header in enumerate(headers):
        draw.rectangle([x, top, x + col_widths[index], top + row_height], outline="black", width=2)
        draw.text((x + 10, top + 9), header, fill="black", font=font)
        x += col_widths[index]
    for row_index, row in enumerate(rows):
        y = top + row_height * (row_index + 1)
        x = left
        for col_index, value in enumerate(row):
            draw.rectangle([x, y, x + col_widths[col_index], y + row_height], outline="black", width=2)
            draw.text((x + 10, y + 9), value, fill="black", font=font)
            x += col_widths[col_index]
    image.save(path)
    return path


def main() -> None:
    out = Path(__file__).resolve().parent / "samples"
    out.mkdir(exist_ok=True)

    make_table_image(
        out / "sales.png",
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
        out / "inventory.png",
        "Inventory 库存表",
        ["物料名称", "数量", "单价", "占比"],
        [
            ["螺丝 M8", "1,024", "¥12.50", "42.5%"],
            ["垫圈 6mm", "512", "¥3.75", "18.0%"],
            ["轴承 6202", "78", "¥45.00", "9.5%"],
        ],
    )
    print(f"samples written to {out}")


if __name__ == "__main__":
    main()
