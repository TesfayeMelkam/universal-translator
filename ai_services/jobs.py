"""Tiny in-memory background job runner for slow work (subtitles). One server process, no database."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from .providers.base import ProviderError


@dataclass
class Job:
    id: str
    created: float
    status: str = "queued"                  # queued | running | done | error
    progress: float = 0.0
    note: str = ""
    error: Optional[dict] = None
    result: Optional[dict] = None
    owner: int = 0


class JobManager:
    def __init__(self, max_running: int = 2, max_kept: int = 20, ttl: float = 3600, clock=time.time, run_async=True):
        self.max_running, self.max_kept, self.ttl, self.clock, self.run_async = max_running, max_kept, ttl, clock, run_async
        self.jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def _purge(self):
        now = self.clock()
        for jid in [j for j, job in self.jobs.items() if now - job.created > self.ttl and job.status in ("done", "error")]:
            del self.jobs[jid]
        while len(self.jobs) > self.max_kept:
            oldest = min((j for j in self.jobs.values() if j.status in ("done", "error")), key=lambda j: j.created, default=None)
            if not oldest:
                break
            del self.jobs[oldest.id]

    def submit(self, fn: Callable[[Callable[[float, str], None]], dict], owner: int = 0) -> str:
        with self._lock:
            self._purge()
            if sum(1 for j in self.jobs.values() if j.status in ("queued", "running")) >= self.max_running:
                raise ProviderError("busy", "The server is busy with other files. Try again in a few minutes.", 429)
            job = Job(secrets.token_urlsafe(9), self.clock(), owner=owner)
            self.jobs[job.id] = job

        def report(p: float, note: str = ""):
            job.progress, job.note = max(0.0, min(1.0, p)), note

        def run():
            job.status = "running"
            try:
                job.result = fn(report)
                job.status, job.progress = "done", 1.0
            except ProviderError as exc:
                job.status, job.error = "error", {"code": exc.code, "message": exc.message}
            except Exception:  # noqa: BLE001
                job.status, job.error = "error", {"code": "job_failed", "message": "Processing failed."}

        if self.run_async:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return job.id

    def get(self, job_id: str, owner: int = 0) -> Job:
        job = self.jobs.get(job_id)
        if not job or job.owner != owner:
            raise ProviderError("job_not_found", "That job does not exist or has expired.", 404)
        return job

    def status(self, job_id: str, owner: int = 0) -> dict:
        j = self.get(job_id, owner)
        d = {"id": j.id, "status": j.status, "progress": round(j.progress, 3), "note": j.note, "error": j.error}
        if j.status == "done" and j.result:
            d["segments"] = j.result.get("segments")
            d["translated"] = j.result.get("translated")
        return d
