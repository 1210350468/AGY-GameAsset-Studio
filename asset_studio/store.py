import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.lock = RLock()
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL,
                    params TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    def create(self, job_id: str, title: str, kind: str, mode: str, params: dict[str, Any]) -> None:
        now = timestamp()
        with self.lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs (id,title,kind,mode,status,stage,progress,params,error,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, title, kind, mode, "queued", "queued", 0.0, json.dumps(params, ensure_ascii=False), None, now, now),
            )

    def update(self, job_id: str, *, status: str, stage: str, progress: float, error: str | None = None) -> None:
        with self.lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status=?,stage=?,progress=?,error=?,updated_at=? WHERE id=?",
                (status, stage, progress, error, timestamp(), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["params"] = json.loads(result["params"])
        return result

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["params"] = json.loads(item["params"])
            results.append(item)
        return results

    def recover_interrupted(self) -> None:
        with self.lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET status='failed',stage='interrupted',"
                "error='服务进程中断，请重新提交此任务',updated_at=? WHERE status='running'",
                (timestamp(),),
            )

