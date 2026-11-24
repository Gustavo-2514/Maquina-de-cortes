from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from ..config import get_settings, load_user_settings
from ..db import get_session
from ..models import Download, Job, now
from ..queue import FINISHED, active_job_for, cancel_job, enqueue, latest_job_for, retry_job
from ..schemas import DownloadBatch, DownloadCreate, InfoRequest
from ..services import downloader

router = APIRouter(prefix="/downloads", tags=["downloads"])
log = logging.getLogger(__name__)


def _get(session: Session, dl_id: int) -> Download:
    dl = session.get(Download, dl_id)
    if dl is None:
        raise HTTPException(404, "Download não encontrado")
    return dl


@router.post("/info")
def info(body: InfoRequest) -> dict:
    """Metadados sem baixar (roda em threadpool: chamada de rede bloqueante)."""
    try:
        return downloader.extract_info(body.url.strip(), load_user_settings().cookies_path)
    except downloader.FriendlyError as e:
        raise HTTPException(422, {"message": str(e), "detail": e.detail}) from e


def _create(session: Session, item: DownloadCreate) -> Download:
    dl = Download(
        url=item.url.strip(), format_choice=item.format_choice, send_to_project=item.send_to_project,
        title=item.title, uploader=item.uploader, duration_s=item.duration_s, thumbnail_url=item.thumbnail_url,
    )
    session.add(dl)
    session.commit()
    session.refresh(dl)
    enqueue(session, "download", dl.id)  # type: ignore[arg-type]
    session.refresh(dl)  # commit expira o objeto; sem refresh ele serializa vazio
    return dl


@router.post("", response_model=Download)
def create(body: DownloadCreate, session: Session = Depends(get_session)) -> Download:
    return _create(session, body)


@router.post("/batch", response_model=list[Download])
def create_batch(body: DownloadBatch, session: Session = Depends(get_session)) -> list[Download]:
    created = [_create(session, item) for item in body.items]
    for dl in created:
        session.refresh(dl)
    return created


@router.get("", response_model=list[Download])
def list_downloads(limit: int = 200, session: Session = Depends(get_session)) -> list[Download]:
    return list(session.exec(select(Download).order_by(col(Download.id).desc()).limit(limit)).all())


@router.get("/{dl_id}", response_model=Download)
def get_download(dl_id: int, session: Session = Depends(get_session)) -> Download:
    return _get(session, dl_id)


@router.post("/{dl_id}/cancel", response_model=Download)
def cancel(dl_id: int, session: Session = Depends(get_session)) -> Download:
    dl = _get(session, dl_id)
    job = active_job_for(session, "download", dl_id)
    if job:
        cancel_job(session, job)
    elif dl.status not in FINISHED:
        dl.status, dl.updated_at = "canceled", now()
        session.add(dl)
        session.commit()
    session.refresh(dl)
    return dl


@router.post("/{dl_id}/retry", response_model=Download)
def retry(dl_id: int, session: Session = Depends(get_session)) -> Download:
    dl = _get(session, dl_id)
    if dl.status not in ("error", "canceled"):
        raise HTTPException(409, "Só é possível repetir downloads com erro ou cancelados")
    job = latest_job_for(session, "download", dl_id)
    if job and job.status in ("error", "canceled"):
        retry_job(session, job)
    else:
        dl.status, dl.progress, dl.error, dl.updated_at = "queued", 0, "", now()
        session.add(dl)
        session.commit()
        enqueue(session, "download", dl_id)
    session.refresh(dl)
    return dl


def _safe_data_path(p: str) -> Path | None:
    if not p:
        return None
    path = Path(p).resolve()
    return path if path.is_relative_to(get_settings().data_dir.resolve()) else None


@router.delete("/{dl_id}")
def delete(dl_id: int, delete_file: bool = False, session: Session = Depends(get_session)) -> dict:
    dl = _get(session, dl_id)
    job = active_job_for(session, "download", dl_id)
    if job:
        cancel_job(session, job)
    removed = False
    if delete_file:
        path = _safe_data_path(dl.file_path)
        if path and path.is_file():
            if dl.project_id:
                raise HTTPException(409, "Este arquivo é usado por um projeto; apague o projeto antes.")
            path.unlink()
            removed = True
    session.delete(dl)
    for j in session.exec(select(Job).where(Job.type == "download", Job.ref_id == dl_id)).all():
        session.delete(j)  # já cancelado acima, se estava ativo
    session.commit()
    return {"ok": True, "file_removed": removed}
