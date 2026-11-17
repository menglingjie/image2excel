# 图片转 Excel 服务

上传图片（截图、扫描件、报表照片），自动识别其中的表格并导出 `.xlsx`。

服务跑在 FastAPI 上，带一个单页网页界面：拖图 → 转换 → 预览 → 下载。

## 识别引擎

只保留 **PaddleOCR**（PP-StructureV3 版面分析 + OCR，再按文本框坐标 + 表格线重建网格）：
中英文都准，无边框表格也能还原；26 列 × 46 行、单元格只有 10px 高的密表也能完整还原。

`paddle` 引擎的做法不是直接用 PP-StructureV3 输出的 HTML（密表上它会漏行、串列），而是：

1. 版面模型找出表格区域；
2. OCR 出所有文本框（坐标 + 文字）；
3. **竖直表格线**确定列边界（能保住空列，例如整列为空的「姓名」列），没有表格线时退化为按 x 聚类；
4. OCR 文本框按 y 聚类成行；
5. 文本框落格，多行表头自动合并成一格。

## 快速开始

```bash
cd /data/workspace/image2excel
./run.sh                 # 首次运行会自动建虚拟环境、装依赖
PORT=8080 ./run.sh       # 换端口
```

服务起来后打开 http://<host>:8000 。

## 命令行用法

```bash
.venv/bin/python -m app.cli 图片.png -o 结果.xlsx
.venv/bin/python -m app.cli ./截图目录/ -o 结果.xlsx --merge-all
```

## HTTP 接口

```bash
# 上传并转换
curl -X POST http://127.0.0.1:8000/api/convert \
  -F "files=@a.png" -F "files=@b.png" \
  -F "engine=paddle" -F "header=true" -F "merge_all=false"
# => {"id":"54e57be4f18f","status":"processing",...}

# 轮询状态（带预览数据）
curl http://127.0.0.1:8000/api/jobs/54e57be4f18f

# 下载 Excel
curl -OJ http://127.0.0.1:8000/api/jobs/54e57be4f18f/download
```

| 接口 | 说明 |
| --- | --- |
| `GET /api/engines` | 可用引擎列表 |
| `POST /api/convert` | 上传图片，返回任务 id |
| `GET /api/jobs/{id}` | 任务状态与识别结果（预览用） |
| `GET /api/jobs/{id}/download` | 下载 `.xlsx` |

上传参数：`engine`（`paddle`）、`header`（首行当表头）、
`merge_all`（全部表格合到一个工作表）、`include_titles`、`include_source`。

## 导出的 Excel

- 第一个工作表是「目录」：源文件、表名、行数、列数、所在工作表。
- 每个表格一个工作表（`图1-表1`），或按需全部合并到「全部表格」。
- 表头加粗、蓝底白字，冻结首行、自动筛选、边框、按内容自动列宽。
- 单元格自动转类型：`1,250` → 数字 1250，`¥12.50` → 数字 + 货币格式，
  `42.5%` → 0.425 + 百分比格式，`2026-10-01` → 日期。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `I2E_PADDLE_ENABLED` | `1` | 关掉就不再识别（没有其它引擎兜底） |
| `I2E_PADDLE_LAYOUT` | `PP-DocLayout-L` | 版面分析模型 |
| `I2E_PADDLE_DET` / `I2E_PADDLE_REC` | `PP-OCRv5_mobile_det` / `PP-OCRv5_server_rec` | OCR 模型 |
| `I2E_PADDLE_TARGET_SIDE` | `2560` | 检测时把图片长边缩放到多少像素（越小越快） |
| `I2E_PADDLE_MAX_CANDIDATES` | `20000` | 文本框数量上限，Paddle 默认 1000 会把密表的表头挤掉 |
| `I2E_MAX_UPLOAD_MB` | `20` | 单张图片上限 |
| `I2E_MAX_FILES` | `10` | 单次上传张数上限 |
| `I2E_JOB_TTL` | `21600` | 任务与上传文件保留时间（秒，默认 6 小时） |
| `I2E_CLEANUP_INTERVAL` | `300` | 后台自动清理间隔（秒） |

后台线程按间隔清理过期任务和 `storage/` 下的过期目录（包括服务重启前遗留的目录），无需等新上传触发。

## 代码结构

```
app/
  main.py         FastAPI 服务（上传、任务、下载）
  extract.py      识别入口（PaddleOCR 引擎调度）
  paddle_engine.py PaddleOCR 引擎（版面 + OCR + 网格重建）
  grid.py         文本框 → 行列聚类 → 表格网格（含多行表头合并）
  gridlines.py    表格竖线检测 → 列边界
  tables.py       表格 HTML 解析（含 colspan/rowspan）
  excel.py        xlsx 生成（样式、类型推断）
  cli.py          命令行入口
  static/index.html  网页界面
tests/
  make_samples.py 生成测试图片
  test_pipeline.py 端到端测试
```

## 已知限制

- PaddleOCR 首次运行要下载模型（约 500MB，存在 `~/.paddlex/`），之后走本地缓存。
- 内存占用约 4GB（8GB 机器上没问题），并发推理被串行化以免爆内存。
- 耗时跟单元格数量相关：普通表格 10~20 秒，1200 格的大表约 50 秒。
- 这台机器的 Paddle CPU 推理有一处 oneDNN bug：检测/版面模型一开 oneDNN 就崩，
  代码里对这两个模型关掉 oneDNN、只给识别模型开（识别快 4 倍，见 `app/paddle_engine.py` 的 `_patch_run_mode`）。
- Paddle 推理必须跑在固定线程里（oneDNN 的线程状态不可跨线程复用），
  所以所有识别任务都排队交给一个专用工作线程，见 `run_pipeline`。
- Paddle 默认最多只保留 1000 个文本框，密表会被截掉表头，这里已提到 20000。
- 单元格里有换行的复杂表头会被拍平成一行。
- 极小的单字符（如数字 `1`）在 10px 高的密表里偶尔会被识别成 `-`。
