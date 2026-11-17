# image2excel — 图片转 Excel

FastAPI 单页服务：上传图片 → 识别表格 → 导出 `.xlsx`。代码/文档/README 全中文，注释也写中文。

## 运行

```bash
cd /data/workspace/image2excel
./run.sh                       # 0.0.0.0:8000；PORT=8080 ./run.sh 可换端口
```

`run.sh` 首次运行会 `uv venv --python 3.13` + 装 `requirements.txt` + `sudo apt-get install tesseract-ocr{,-eng,-chi-sim}`。
依赖全在 `.venv`（Python 3.13）；系统层只需要 tesseract 二进制和中文字体（`NotoSansCJK` 等，见 `tests/make_samples.py:FONT_CANDIDATES`）。

- 8000 端口上通常已有 uvicorn 在跑（`ps aux | grep uvicorn`），重启前先 kill，否则端口冲突。
- CLI：`.venv/bin/python -m app.cli 图片.png -o out.xlsx [--engine auto|local|vision|text] [--merge-all] [--no-header]`。
  **CLI 的 `--engine` 没有 `paddle` 选项**（HTTP API 有）；`auto` 的第一顺位就是 paddle，所以直接用 `auto`。
  CLI 用相对 import，必须在仓库根目录运行。

## 测试

没有 pytest、没有 lint / formatter / typecheck 配置。唯一测试是脚本：

```bash
.venv/bin/python tests/test_pipeline.py     # 约 45s（含 Paddle 推理）
```

- 它**每次都会重新生成** `tests/samples/*.png`（`tests/make_samples.py`），不要手改这些图。
- 只有 `paddle` 是严格比对；`local` 是宽松的，而且**当前实际比对不上**（`WidgetA`、`1.25` vs `7.25`、`效量` vs `数量` 这类 Tesseract 误识），报 `~` 不算失败。
- Excel 断言里有一条：任何单元格值都不能以 `=` 开头（防止公式注入）。
- 只跑一个引擎：
  ```bash
  .venv/bin/python -c "import sys; sys.path.insert(0,'.'); from tests.test_pipeline import build_samples, check_engine; build_samples(); check_engine('local', False)"
  ```

## 管线

上传 → 落盘 `storage/<job_id>/` → 后台线程 `process_job`（`app/main.py`）→ `extract.extract_file(engine)` → `excel.build_workbook` → xlsx 字节先存在内存，`/download` 时才写盘。

- 引擎调度在 `app/extract.py:extract_file`：`auto` = paddle → vision → local → text，取第一个有结果的；显式指定引擎时该引擎没结果就直接返回 error。
- `Table.rows` 是矩形 `list[list[str]]`（短行用 `""` 补齐），标题单独放 `Table.title`。API 返回、前端预览、Excel 导出都依赖这个形状——改 `models.py` 要同步三处。
- **paddle 引擎不用 PP-StructureV3 的 HTML 表格结果**（密表上它会漏行串列），只取它的版面框 + OCR 文本框，然后自己重建网格：
  - 列边界 = `app/gridlines.py` 检测到的竖直表格线（这样能保住整列为空的列），没有线才退化为按 x 聚类；
  - 行 = `app/grid.py:cluster_rows` 按 y 聚类；
  - 多行表头由 `grid._merge_header` 合并成一行（前提：表头行不是数字行、行距均匀）。
  - HTML 网格只在重建失败时兜底；`app/tables.py` 仅用于解析那份 HTML（展开 colspan/rowspan）。

## Paddle 硬约束（动这块代码前先读 `app/paddle_engine.py`）

- **推理必须跑在固定的一个线程**：oneDNN 线程状态不可跨线程复用，所以所有识别任务都进 `_QUEUE` 交给单个 `paddle-worker` 线程串行执行。不要新建线程并发跑 Paddle，也不要绕过 `run_pipeline`。
- 本机 CPU 上 det/版面模型开 oneDNN 会崩。`_patch_run_mode()` 把 paddlex 的 `get_default_run_mode` 改成只有 `*_rec` 用 mkldnn、其余用 paddle（识别快约 4 倍）。这是对 paddlex **私有路径**的 monkeypatch，升级 paddlex 后要重新验证是否还生效。
- `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False` 等环境变量必须在 import paddlex **之前**设置，所以 paddle 的 import 全是懒加载（`get_pipeline()` 里才 `from paddleocr import PPStructureV3`）。新增代码不要在模块顶层 import paddleocr/paddlex。
- Paddle 默认只保留 1000 个文本框，密表会被截掉表头；`_raise_detection_cap()` 把 `post_op.max_candidates` 提到 20000。同样依赖私有属性，失效时是**静默**的（不会报错，只是表格变差）。
- 模型缓存在 `~/.paddlex/`（已占 2.5G），首次运行下载约 500MB；推理内存约 4GB。

## Excel 导出（`app/excel.py`）

- 第一个工作表固定叫「目录」，之后每表一个 sheet（`图1-表1` 或 `图1-<标题>`）；`merge_all` 时全部合到「全部表格」。
- 类型推断在 `excel.convert_cell`：`1,250`→1250、`¥12.50`→数值+货币格式、`42.5%`→0.425+百分比格式、`2026-10-01`→date。
- **以 `=` 开头的文本会原样写入，openpyxl 当成公式**——OCR 结果若出现这种内容要么转义要么清掉。
- sheet 名走 `safe_sheet_name`（去非法字符、截 31 字符、重名加 `~2` 后缀），新 sheet 名请沿用它。

## 配置与杂项

- 环境变量全在 `app/config.py` 顶部读取，**import 时求值**：进程内改 `os.environ` 不生效，要重启。
- README 的环境变量表不完整，**以 `app/config.py` 为准**（另有 `I2E_STORAGE_DIR`、`I2E_OCR_THREADS`、`I2E_PADDLE_LANG`、`I2E_PADDLE_REC_BATCH`、`I2E_VISION_TIMEOUT`）。
- `I2E_STORAGE_DIR`（默认 `storage/`）存放上传原图和导出的 xlsx，按 job id 分目录。
- 任务状态只在进程内存（`app/main.py:jobs`，6 小时 TTL，且只在新任务到来时清理）。重启服务后旧 job id 失效，但 `storage/` 里的文件会留下。
- 前端是单文件原生 JS（`app/static/index.html`），没有构建步骤，改 UI 直接改这个文件；它靠 `/api/engines`、`/api/convert`、`/api/jobs/{id}`、`/api/jobs/{id}/download` 四个接口。
- 这个目录**不是 git 仓库**（没有 `.git`），提交/分支相关的事先问用户。
