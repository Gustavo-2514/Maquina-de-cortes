from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, col, select

from ..config import get_settings
from ..db import get_session
from ..models import Download, Project, now
from ..config import load_user_settings
from ..estimate import estimate
from ..project_ops import (VIDEO_EXTS, ProjectError, create_project, delete_project, media_files, prepare_media,
                           project_from_download, start_analysis)
from ..schemas import AnalysisOptions, ProjectCreate, ProjectUpdate

router = APIRouter(tags=["projects"])


def _get(session: Session, pid: int) -> Project:
    p = session.get(Project, pid)
    if p is None:
        raise HTTPException(404, "Projeto não encontrado")
    return p


def _err(e: ProjectError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/projects", response_model=list[Project])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.exec(select(Project).order_by(col(Project.id).desc())).all())


@router.get("/projects/{pid}", response_model=Project)
def get_project(pid: int, session: Session = Depends(get_session)) -> Project:
    return _get(session, pid)


@router.post("/projects", response_model=Project)
def create(body: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    body.language = body.language or load_user_settings().default_language
    try:
        if body.download_id is not None:
            dl = session.get(Download, body.download_id)
            if dl is None:
                raise HTTPException(404, "Download não encontrado")
            p = project_from_download(session, dl, body.language)
            if body.name.strip():
                p.name = body.name.strip()[:200]
                session.add(p)
                session.commit()
        elif body.local_path:
            path = Path(body.local_path.strip().strip('"').strip("'")).expanduser()
            if not path.is_file():
                raise HTTPException(404, f"Arquivo não encontrado: {path}")
            if path.suffix.lower() not in VIDEO_EXTS:
                raise HTTPException(422, f"Extensão não suportada: {path.suffix or '(nenhuma)'}")
            p = create_project(session, name=body.name or path.stem, source_path=path.resolve(),
                               origin="local_path", language=body.language)
        else:
            raise HTTPException(422, "Informe download_id ou local_path (ou use /projects/upload)")
        if body.analyze:
            start_analysis(session, p, body.analyze)
    except ProjectError as e:
        raise _err(e) from e
    session.refresh(p)
    return p


@router.post("/downloads/{dl_id}/to-project", response_model=Project)
def download_to_project(dl_id: int, session: Session = Depends(get_session)) -> Project:
    dl = session.get(Download, dl_id)
    if dl is None:
        raise HTTPException(404, "Download não encontrado")
    try:
        return project_from_download(session, dl, load_user_settings().default_language)
    except ProjectError as e:
        raise _err(e) from e


_SAFE_NAME = re.compile(r"[^\w.\- ]+", re.UNICODE)


@router.post("/projects/upload", response_model=Project)
async def upload(request: Request, filename: str, name: str = "", language: str = "",
                 session: Session = Depends(get_session)) -> Project:
    """Upload em streaming (corpo cru, sem multipart) — não carrega o arquivo na memória."""
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise HTTPException(422, f"Extensão não suportada: {ext or '(nenhuma)'}")
    stem = _SAFE_NAME.sub("_", Path(filename).stem)[:80] or "video"
    p = Project(name=(name or Path(filename).stem)[:200], source_path="", origin="upload",
                language=language or load_user_settings().default_language)
    session.add(p)
    session.commit()
    session.refresh(p)
    pdir = get_settings().project_dir(p.id)  # type: ignore[arg-type]
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / f"source{ext}"
    tmp = pdir / f"upload.{stem}.part"
    size = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                size += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        session.delete(p)
        session.commit()
        raise
    if size == 0:
        tmp.unlink(missing_ok=True)
        session.delete(p)
        session.commit()
        raise HTTPException(422, "Arquivo vazio")
    tmp.replace(dest)
    p.source_path, p.updated_at = str(dest), now()
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.patch("/projects/{pid}", response_model=Project)
def patch(pid: int, body: ProjectUpdate, session: Session = Depends(get_session)) -> Project:
    p = _get(session, pid)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    p.updated_at = now()
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.delete("/projects/{pid}")
def delete(pid: int, session: Session = Depends(get_session)) -> dict:
    delete_project(session, _get(session, pid))
    return {"ok": True}


@router.post("/projects/{pid}/analyze", response_model=Project)
def analyze(pid: int, body: AnalysisOptions, session: Session = Depends(get_session)) -> Project:
    if body.min_s >= body.max_s:
        raise HTTPException(422, "A duração mínima precisa ser menor que a máxima")
    p = _get(session, pid)
    if not p.source_path:
        raise HTTPException(409, "O upload deste projeto não terminou")
    start_analysis(session, p, body)
    session.refresh(p)
    return p


def _transcript_path(pid: int) -> Path:
    return get_settings().project_dir(pid) / "transcript.json"


@router.get("/projects/{pid}/transcript")
def get_transcript(pid: int, session: Session = Depends(get_session)) -> dict:
    _get(session, pid)
    path = _transcript_path(pid)
    if not path.exists():
        raise HTTPException(404, "Transcrição ainda não existe")
    return json.loads(path.read_text(encoding="utf-8"))


@router.put("/projects/{pid}/transcript")
def put_transcript(pid: int, body: dict, session: Session = Depends(get_session)) -> dict:
    """Correções manuais: só o texto das palavras muda; tempos e estrutura são preservados."""
    _get(session, pid)
    path = _transcript_path(pid)
    if not path.exists():
        raise HTTPException(404, "Transcrição ainda não existe")
    current = json.loads(path.read_text(encoding="utf-8"))
    new_segs = body.get("segments")
    if not isinstance(new_segs, list) or len(new_segs) != len(current["segments"]):
        raise HTTPException(422, "Estrutura da transcrição não confere")
    for seg, new in zip(current["segments"], new_segs, strict=True):
        words = new.get("words") if isinstance(new, dict) else None
        if not isinstance(words, list) or len(words) != len(seg["words"]):
            raise HTTPException(422, f"Segmento {seg['id']}: número de palavras não confere")
        for w, nw in zip(seg["words"], words, strict=True):
            text = str(nw.get("w", "")).strip()
            if text:
                w["w"] = text[:100]
        seg["text"] = " ".join(w["w"] for w in seg["words"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return current


@router.get("/projects/{pid}/waveform")
def waveform(pid: int, session: Session = Depends(get_session)) -> dict:
    _get(session, pid)
    path = get_settings().project_dir(pid) / "waveform.json"
    if not path.exists():
        raise HTTPException(404, "Forma de onda ainda não existe")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/projects/{pid}/thumbs")
def thumbs(pid: int, session: Session = Depends(get_session)) -> dict:
    _get(session, pid)
    d = get_settings().project_dir(pid) / "thumbs"
    files = sorted(f.name for f in d.glob("*.jpg")) if d.is_dir() else []
    return {"every_s": 10, "urls": [f"/api/media/projects/{pid}/thumbs/{n}" for n in files]}


@router.get("/projects/{pid}/estimate")
def get_estimate(pid: int, language: str = "pt", session: Session = Depends(get_session)) -> dict:
    """Tempo estimado da análise (o que já está em cache conta como 0)."""
    p = _get(session, pid)
    duration = p.duration_s
    if not duration and p.source_path:
        from ..services import probe

        try:
            duration = probe.probe(Path(p.source_path)).duration_s
        except probe.ProbeError:
            duration = None
    if not duration:
        raise HTTPException(409, "Duração do vídeo desconhecida")
    return estimate(get_settings().project_dir(pid), duration, language, load_user_settings())


@router.get("/projects/{pid}/files")
def get_files(pid: int, session: Session = Depends(get_session)) -> dict:
    _get(session, pid)
    return media_files(pid)


@router.post("/projects/{pid}/prepare", response_model=Project)
def prepare(pid: int, session: Session = Depends(get_session)) -> Project:
    """Regera proxy/áudio apagados pela limpeza de disco (sem refazer transcrição/análise)."""
    p = _get(session, pid)
    try:
        prepare_media(session, p)
    except ProjectError as e:
        raise _err(e) from e
    session.refresh(p)
    return p
