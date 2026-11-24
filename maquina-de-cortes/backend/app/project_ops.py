"""Criação de projetos e início da análise — usado pela API e pelo worker (download → projeto)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from sqlmodel import Session, col, select

from .config import get_settings
from .models import Clip, Download, Job, Project, now
from .queue import cancel_job, enqueue
from .schemas import AnalysisOptions

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".ts", ".wmv", ".mpg", ".mpeg", ".3gp"}
PIPELINE_JOBS = ("probe_proxy", "transcribe", "analyze", "reframe")


class ProjectError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def create_project(session: Session, *, name: str, source_path: Path, origin: str,
                   download_id: int | None = None, language: str = "pt") -> Project:
    p = Project(name=name.strip()[:200] or source_path.stem, source_path=str(source_path), origin=origin,
                download_id=download_id, language=language or "pt")
    session.add(p)
    session.commit()
    session.refresh(p)
    get_settings().project_dir(p.id).mkdir(parents=True, exist_ok=True)  # type: ignore[arg-type]
    if download_id:
        dl = session.get(Download, download_id)
        if dl:
            dl.project_id, dl.updated_at = p.id, now()
            session.add(dl)
            session.commit()
    session.refresh(p)
    return p


def project_from_download(session: Session, dl: Download, language: str = "pt") -> Project:
    if dl.status != "done" or not dl.file_path:
        raise ProjectError("O download ainda não terminou.", 409)
    path = Path(dl.file_path)
    if not path.is_file():
        raise ProjectError("O arquivo deste download não existe mais.", 404)
    if dl.format_choice == "audio_mp3" or path.suffix.lower() in (".mp3", ".m4a", ".opus", ".wav"):
        raise ProjectError("Este download é só áudio; baixe em vídeo para criar cortes.", 422)
    if dl.project_id and session.get(Project, dl.project_id):
        raise ProjectError("Já existe um projeto para este download.", 409)
    return create_project(session, name=dl.title or path.stem, source_path=path, origin="download",
                          download_id=dl.id, language=language)


def start_analysis(session: Session, project: Project, options: AnalysisOptions | None = None) -> Job:
    """Grava as opções e enfileira o pipeline (probe_proxy → transcribe → [analyze na Fase 3])."""
    if options is None:
        options = AnalysisOptions(language=project.language)
    for j in active_pipeline_jobs(session, project.id):  # type: ignore[arg-type]
        cancel_job(session, j)
    project.settings_json = options.model_dump_json()
    project.language = options.language
    project.status, project.stage, project.progress = "processing", "probe", 0
    project.prepare_only = False
    project.error = project.error_detail = ""
    project.updated_at = now()
    session.add(project)
    session.commit()
    return enqueue(session, "probe_proxy", project.id, priority=1)  # type: ignore[arg-type]


def active_pipeline_jobs(session: Session, project_id: int) -> list[Job]:
    return list(session.exec(select(Job).where(
        col(Job.type).in_(PIPELINE_JOBS), Job.ref_id == project_id, col(Job.status).in_(["queued", "running"])
    )).all())


def delete_project(session: Session, project: Project) -> None:
    pdir = get_settings().project_dir(project.id)  # type: ignore[arg-type]
    if project.download_id:
        dl = session.get(Download, project.download_id)
        if dl and dl.project_id == project.id:
            dl.project_id, dl.updated_at = None, now()
            session.add(dl)
    # apaga todos os jobs do projeto (o SQLite reaproveita ids; um job antigo não pode apontar para outro
    # projeto). Um job em execução cujo registro some é interrompido pelo worker.
    for j in session.exec(select(Job).where(col(Job.type).in_(PIPELINE_JOBS), Job.ref_id == project.id)).all():
        session.delete(j)
    for c in session.exec(select(Clip).where(Clip.project_id == project.id)).all():
        for j in session.exec(select(Job).where(Job.type == "render", Job.ref_id == c.id)).all():
            session.delete(j)
        session.delete(c)
    session.delete(project)
    session.commit()
    # só apaga a pasta do projeto (derivados + upload); download/caminho local ficam intactos
    if pdir.is_dir() and pdir.resolve().is_relative_to(get_settings().data_dir.resolve()):
        shutil.rmtree(pdir, ignore_errors=True)


def options_of(project: Project) -> AnalysisOptions:
    try:
        return AnalysisOptions.model_validate(json.loads(project.settings_json or "{}"))
    except ValueError:
        return AnalysisOptions(language=project.language)


def prepare_media(session: Session, project: Project) -> Job:
    """Regera proxy/áudio/miniaturas apagados pela limpeza de disco, sem refazer transcrição nem análise."""
    if active_pipeline_jobs(session, project.id):  # type: ignore[arg-type]
        raise ProjectError("Este projeto já está sendo processado.", 409)
    project.prepare_only = True
    project.status, project.stage, project.progress = "processing", "probe", 0
    project.updated_at = now()
    session.add(project)
    session.commit()
    return enqueue(session, "probe_proxy", project.id, priority=2)  # type: ignore[arg-type]


def media_files(project_id: int) -> dict:
    pdir = get_settings().project_dir(project_id)
    thumbs = pdir / "thumbs"
    return {"proxy": (pdir / "proxy.mp4").exists(), "audio": (pdir / "audio.wav").exists(),
            "waveform": (pdir / "waveform.json").exists(), "thumbs": thumbs.is_dir() and any(thumbs.glob("*.jpg")),
            "transcript": (pdir / "transcript.json").exists(), "faces": (pdir / "faces.json").exists()}
