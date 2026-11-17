import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ALLOWED_SUFFIXES, MAX_FILES, MAX_UPLOAD_MB, STATIC_DIR, STORAGE_DIR
from .excel import build_workbook
from .extract import engines, extract_file

app = FastAPI(title="图片转 Excel 服务", version="1.0.0")

jobs: dict[str, "Job"] = {}
jobs_lock = threading.Lock()
JOB_TTL_SECONDS = 6 * 3600


@dataclass
class Job:
    id: str
    status: str = "processing"
    created_at: float = field(default_factory=time.time)
    options: dict = field(default_factory=dict)
    files: list = field(default_factory=list)
    error: str = ""
    xlsx_name: str = "result.xlsx"
    xlsx_bytes: bytes | None = None

    def summary(self) -> dict:
        tables = sum(len(f.tables) for f in self.files)
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "table_count": tables,
            "file_count": len(self.files),
            "created_at": self.created_at,
        }

    def detail(self) -> dict:
        data = self.summary()
        data["options"] = self.options
        data["files"] = [f.__dict__ for f in self.files]
        return data


def cleanup_jobs() -> None:
    now = time.time()
    with jobs_lock:
        stale = [job_id for job_id, job in jobs.items() if now - job.created_at > JOB_TTL_SECONDS]
        for job_id in stale:
            jobs.pop(job_id, None)
            shutil.rmtree(STORAGE_DIR / job_id, ignore_errors=True)


def process_job(job: Job, paths: list[Path]) -> None:
    try:
        results = []
        for path in paths:
            results.append(extract_file(path, job.options.get("engine", "auto")))
        job.files = results
        job.xlsx_bytes = build_workbook(results, job.options)
        job.status = "done"
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
    finally:
        with jobs_lock:
            jobs[job.id] = job


@app.get("/api/engines")
def list_engines() -> dict:
    return {"engines": engines()}


@app.post("/api/convert")
def convert(
    files: list[UploadFile] = File(...),
    engine: str = Form("auto"),
    merge_all: bool = Form(False),
    header: bool = Form(True),
    include_titles: bool = Form(True),
    include_source: bool = Form(True),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="没有收到文件")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_FILES} 张图片")
    if engine not in ("auto", "paddle", "local", "vision", "text"):
        raise HTTPException(status_code=400, detail="未知的识别引擎")

    job_id = uuid.uuid4().hex[:12]
    job_dir = STORAGE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    limit = MAX_UPLOAD_MB * 1024 * 1024
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {suffix or '未知'}，仅支持 {', '.join(sorted(ALLOWED_SUFFIXES))}",
            )
        content = upload.file.read()
        if len(content) > limit:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=f"{upload.filename} 超过 {MAX_UPLOAD_MB}MB 限制")
        target = job_dir / Path(upload.filename or f"upload{suffix}").name
        target.write_bytes(content)
        saved.append(target)

    job = Job(
        id=job_id,
        options={
            "engine": engine,
            "merge_all": merge_all,
            "header": header,
            "include_titles": include_titles,
            "include_source": include_source,
        },
    )
    with jobs_lock:
        jobs[job_id] = job
    cleanup_jobs()
    threading.Thread(target=process_job, args=(job, saved), daemon=True).start()
    return job.summary()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job.detail()


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if job.status != "done" or not job.xlsx_bytes:
        raise HTTPException(status_code=409, detail="任务尚未完成")
    target = STORAGE_DIR / job_id / job.xlsx_name
    if not target.exists():
        target.write_bytes(job.xlsx_bytes)
    return FileResponse(
        target,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=job.xlsx_name,
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
