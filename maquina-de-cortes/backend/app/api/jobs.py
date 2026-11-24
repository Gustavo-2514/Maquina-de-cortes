from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

from ..db import get_session
from ..events import broker
from ..models import Job
from ..queue import cancel_job, job_target, retry_job

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 300, session: Session = Depends(get_session)) -> list[dict]:
    q = select(Job)
    if status:
        q = q.where(col(Job.status).in_(status.split(",")))
    jobs = session.exec(q.order_by(col(Job.id).desc()).limit(limit)).all()
    return [{**j.model_dump(mode="json"), **job_target(session, j)} for j in jobs]


def _get(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job não encontrado")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel(job_id: int, session: Session = Depends(get_session)) -> Job:
    return cancel_job(session, _get(session, job_id))


@router.post("/jobs/{job_id}/retry", response_model=Job)
def retry(job_id: int, session: Session = Depends(get_session)) -> Job:
    job = _get(session, job_id)
    if job.status not in ("error", "canceled"):
        raise HTTPException(409, "Só é possível repetir jobs com erro ou cancelados")
    return retry_job(session, job)


@router.get("/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        broker.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
