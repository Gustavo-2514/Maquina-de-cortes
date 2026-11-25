"""Operações da fila de jobs compartilhadas por API e worker (seção 7).

A fila é a própria tabela `job`. A API só enfileira/cancela/repete; quem executa é o worker.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import Session, col, select

import json

from .models import CLIP_JOB_TYPES, GPU_JOB_TYPES, Clip, Download, Job, Project, now

FINISHED = {"done", "error", "canceled"}


def enqueue(session: Session, type_: str, ref_id: int, priority: int = 0, message: str = "Na fila",
            params: dict | None = None) -> Job:
    job = Job(type=type_, ref_id=ref_id, uses_gpu=type_ in GPU_JOB_TYPES, priority=priority, message=message,
              params_json=json.dumps(params or {}))
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def cancel_job(session: Session, job: Job) -> Job:
    """Marca como cancelado. Se estiver rodando, o worker percebe e interrompe o handler."""
    if job.status in FINISHED:
        return job
    was_queued = job.status == "queued"
    job.status = "canceled"
    job.message = "Cancelado"
    job.finished_at = now()
    job.updated_at = now()
    session.add(job)
    if job.type == "download" and was_queued:
        # job nunca rodou: o handler não vai atualizar o download, então fazemos aqui
        dl = session.get(Download, job.ref_id)
        if dl and dl.status not in FINISHED:
            dl.status, dl.updated_at = "canceled", now()
            session.add(dl)
    session.commit()
    session.refresh(job)
    return job


def retry_job(session: Session, job: Job) -> Job:
    if job.status not in ("error", "canceled"):
        return job
    job.status, job.progress, job.message = "queued", 0, "Na fila (repetição)"
    job.error = job.error_detail = ""
    job.started_at = job.finished_at = None
    job.updated_at = now()
    session.add(job)
    if job.type == "download":
        dl = session.get(Download, job.ref_id)
        if dl:
            dl.status, dl.progress, dl.error, dl.error_detail = "queued", 0, "", ""
            dl.speed = dl.eta = ""
            dl.updated_at = now()
            session.add(dl)
    session.commit()
    session.refresh(job)
    return job


def active_job_for(session: Session, type_: str, ref_id: int) -> Job | None:
    return session.exec(
        select(Job).where(Job.type == type_, Job.ref_id == ref_id, col(Job.status).in_(["queued", "running"]))
        .order_by(col(Job.id).desc())
    ).first()


def latest_job_for(session: Session, type_: str, ref_id: int) -> Job | None:
    return session.exec(select(Job).where(Job.type == type_, Job.ref_id == ref_id).order_by(col(Job.id).desc())).first()


def recover_interrupted(session: Session) -> int:
    """Jobs 'running' quando o app caiu voltam para 'queued' (seção 7)."""
    res = session.exec(  # type: ignore[call-overload]
        update(Job).where(col(Job.status) == "running")
        .values(status="queued", message="Retomado após reinício", progress=0, updated_at=now())
    )
    session.exec(  # type: ignore[call-overload]
        update(Download).where(col(Download.status) == "downloading").values(status="queued", updated_at=now())
    )
    session.commit()
    return res.rowcount or 0


def claim(session: Session, gpu: bool, exclude_ids: set[int]) -> Job | None:
    """Pega o próximo job da categoria e marca como running de forma atômica."""
    q = (
        select(Job)
        .where(Job.status == "queued", Job.uses_gpu == gpu)
        .order_by(col(Job.priority).desc(), col(Job.id))
        .limit(5)
    )
    for job in session.exec(q).all():
        if job.id in exclude_ids:
            continue
        res = session.exec(  # type: ignore[call-overload]
            update(Job).where(col(Job.id) == job.id, col(Job.status) == "queued")
            .values(status="running", started_at=now(), updated_at=now(), message="Iniciando…")
        )
        session.commit()
        if res.rowcount == 1:
            session.refresh(job)
            return job
    return None


def job_target(session: Session, job: Job) -> dict:
    """Nome legível do alvo do job + link (para a Fila)."""
    if job.type == "download":
        dl = session.get(Download, job.ref_id)
        return {"target": (dl.title or dl.url) if dl else f"download #{job.ref_id}", "target_link": "/downloads"}
    if job.type in CLIP_JOB_TYPES:
        c = session.get(Clip, job.ref_id)
        p = session.get(Project, c.project_id) if c else None
        name = f"{c.title or 'Corte'}" + (f" · {p.name}" if p else "") if c else f"corte #{job.ref_id}"
        return {"target": name, "target_link": f"/projetos/{c.project_id}" if c else ""}
    p = session.get(Project, job.ref_id)
    return {"target": p.name if p else f"projeto #{job.ref_id}", "target_link": f"/projetos/{job.ref_id}" if p else ""}
