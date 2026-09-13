"""In-process background jobs with pollable progress.

Enrichment is slow in a way uploads never were - one LLM call per batch of ten
products, so a 200-product catalog is minutes, not milliseconds. Holding the
HTTP request open for that would time out and leave the seller staring at a
spinner with no idea whether anything is happening.

Deliberately minimal: a dict guarded by a lock, and a worker thread. No Celery,
no Redis, no broker. The app is single-process uvicorn on the seller's own
machine, and the work is not durable-critical - if the process restarts
mid-enrichment, re-running is cheap because everything upstream is cached.
Reach for a real queue when there are multiple workers or jobs that must
survive a restart; neither is true today.

Jobs are kept after completion so the UI can poll once more and read the final
result, and pruned by age so a long-lived process does not accumulate them.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.logging_setup import get_logger

log = get_logger("jobs")

# How long a finished job stays readable. Generous relative to the UI's poll
# interval, short enough that memory does not grow without bound.
RETENTION = timedelta(minutes=30)

_jobs = {}
_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def create_job(kind, total=0, stage="queued"):
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "stage": stage,
            "done": False,
            "ok": None,
            "progress": 0,
            "total": total,
            "message": None,
            "error": None,
            "result": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
    return job_id


def update_job(job_id, **fields):
    """Merge fields into a job. Unknown job ids are ignored rather than raised:
    a progress callback firing after a prune should not kill the worker."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        job["updated_at"] = _now()


def get_job(job_id):
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def prune(now=None):
    now = now or _now()
    with _lock:
        stale = [
            job_id for job_id, job in _jobs.items()
            if job["done"] and now - job["updated_at"] > RETENTION
        ]
        for job_id in stale:
            del _jobs[job_id]
    return len(stale)


def run_in_background(job_id, fn):
    """Run `fn(progress)` on a worker thread.

    `progress(stage=..., progress=..., message=...)` is passed in so the work
    can report where it is without importing this module's internals.

    Any exception is recorded on the job rather than escaping the thread -
    an unhandled error here would otherwise vanish silently and leave the UI
    polling a job that never finishes.
    """

    def progress(**fields):
        update_job(job_id, **fields)

    def worker():
        try:
            result = fn(progress)
            update_job(job_id, done=True, ok=True, stage="complete", result=result)
        except Exception as exc:
            log.exception("job %s failed", job_id)
            update_job(job_id, done=True, ok=False, stage="failed", error=str(exc))

    thread = threading.Thread(target=worker, name=f"job-{job_id[:8]}", daemon=True)
    thread.start()
    prune()
    return thread


def public_view(job):
    """The job as the API exposes it - internal timestamps flattened to ISO
    strings, nothing else stripped."""
    if not job:
        return None
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "stage": job["stage"],
        "done": job["done"],
        "ok": job["ok"],
        "progress": job["progress"],
        "total": job["total"],
        "message": job["message"],
        "error": job["error"],
        "result": job["result"],
        "updated_at": job["updated_at"].isoformat(),
    }
