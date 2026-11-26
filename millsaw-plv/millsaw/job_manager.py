"""
Job manager: persistent storage of cut-job sessions.

Each job lives in <jobs_dir>/<job_id>/ and contains:
    job.json         metadata (created, name, source xlsx, status)
    source.xlsx      the originally uploaded workbook
    *.plv            generated PLV files (one per kept CHOP SAW table)

Jobs are listed in reverse chronological order in the GUI.
"""

from __future__ import annotations
import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional


JOB_META_FILENAME = "job.json"


@dataclass
class JobMeta:
    job_id: str
    created: str
    name: str
    source_filename: str
    status: str = "draft"
    plv_files: List[str] = field(default_factory=list)
    notes: str = ""
    yield_125_pct: float = 80.0
    yield_175_pct: float = 110.0
    yield_250_pct: float = 110.0


def _meta_from_dict(d: dict) -> JobMeta:
    """Construct JobMeta from a dict, tolerating older saved jobs."""
    return JobMeta(
        job_id=d.get("job_id", ""),
        created=d.get("created", ""),
        name=d.get("name", ""),
        source_filename=d.get("source_filename", ""),
        status=d.get("status", "draft"),
        plv_files=list(d.get("plv_files", [])),
        notes=d.get("notes", ""),
        yield_125_pct=float(d.get("yield_125_pct", 80.0)),
        yield_175_pct=float(d.get("yield_175_pct", 110.0)),
        yield_250_pct=float(d.get("yield_250_pct", 110.0)),
    )


class JobManager:
    def __init__(self, jobs_dir):
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id):
        return self.jobs_dir / job_id

    def _meta_path(self, job_id):
        return self._job_path(job_id) / JOB_META_FILENAME

    def create_job(self, source_xlsx, name=""):
        now = datetime.now()
        job_id = now.strftime("%y%m%d_%H%M%S")  # short to avoid Windows MAX_PATH
        suffix = 0
        while (self.jobs_dir / (job_id + (f"_{suffix}" if suffix else ""))).exists():
            suffix += 1
        if suffix:
            job_id = f"{job_id}_{suffix}"
        path = self._job_path(job_id)
        path.mkdir(parents=True)
        src = Path(source_xlsx)
        dst = path / "source.xlsx"
        shutil.copy2(src, dst)
        if not name:
            name = src.stem
        meta = JobMeta(
            job_id=job_id,
            created=now.isoformat(timespec="seconds"),
            name=name,
            source_filename=src.name,
        )
        self._write_meta(meta)
        return meta

    def list_jobs(self):
        out = []
        for sub in sorted(self.jobs_dir.iterdir(), reverse=True):
            if not sub.is_dir():
                continue
            meta_path = sub / JOB_META_FILENAME
            if not meta_path.exists():
                continue
            try:
                d = json.loads(meta_path.read_text(encoding="utf-8"))
                out.append(_meta_from_dict(d))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def get_job(self, job_id):
        meta_path = self._meta_path(job_id)
        if not meta_path.exists():
            return None
        d = json.loads(meta_path.read_text(encoding="utf-8"))
        return _meta_from_dict(d)

    def get_source_path(self, job_id):
        return self._job_path(job_id) / "source.xlsx"

    def get_job_dir(self, job_id):
        return self._job_path(job_id)

    def update_meta(self, meta):
        self._write_meta(meta)

    def add_plv(self, job_id, plv_path):
        meta = self.get_job(job_id)
        if not meta:
            raise KeyError(f"Unknown job: {job_id}")
        src = Path(plv_path)
        dst = self._job_path(job_id) / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        if src.name not in meta.plv_files:
            meta.plv_files.append(src.name)
        meta.status = "processed"
        self._write_meta(meta)
        return dst

    def delete_job(self, job_id):
        path = self._job_path(job_id)
        if path.exists():
            shutil.rmtree(path)

    def _write_meta(self, meta):
        path = self._meta_path(meta.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
