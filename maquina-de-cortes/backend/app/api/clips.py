from __future__ import annotations

import json

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlmodel import Session, col, select

from ..config import get_settings
from ..db import get_session
from ..models import CLIP_JOB_TYPES, CaptionStyle, Clip, Job, Project, now
from ..project_ops import options_of
from ..queue import active_job_for, enqueue
from ..schemas import ApplyTemplate, CaptionStyleIn, CaptionStyleUpdate, ClipCreate, ClipUpdate, PostPackRequest, PostTexts, ReviewRequest, ReviewSubmit
from ..services.highlighter import Words, first_sentence

router = APIRouter(tags=["clips"])

MIN_CLIP_S = 1.0


def _project(session: Session, pid: int) -> Project:
    p = session.get(Project, pid)
    if p is None:
        raise HTTPException(404, "Projeto não encontrado")
    return p


def _clip(session: Session, cid: int) -> Clip:
    c = session.get(Clip, cid)
    if c is None:
        raise HTTPException(404, "Corte não encontrado")
    return c


def _check_range(p: Project, start: float, end: float) -> None:
    if end - start < MIN_CLIP_S:
        raise HTTPException(422, "O fim do corte precisa vir pelo menos 1 s depois do início")
    if p.duration_s and end > p.duration_s + 0.5:
        raise HTTPException(422, "O corte passa do fim do vídeo")


def _hook_for(pid: int, start: float, end: float) -> str:
    path = get_settings().project_dir(pid) / "transcript.json"
    if not path.exists():
        return ""
    words = Words.from_transcript(json.loads(path.read_text(encoding="utf-8")))
    idx = [i for i, w in enumerate(words.w) if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
    return first_sentence(words, idx[0], idx[-1]) if idx else ""


@router.get("/projects/{pid}/clips", response_model=list[Clip])
def list_clips(pid: int, session: Session = Depends(get_session)) -> list[Clip]:
    _project(session, pid)
    return list(session.exec(select(Clip).where(Clip.project_id == pid)
                             .order_by(col(Clip.score).desc(), col(Clip.start_s))).all())


@router.post("/projects/{pid}/clips", response_model=Clip)
def create_clip(pid: int, body: ClipCreate, session: Session = Depends(get_session)) -> Clip:
    """Corte manual (início/fim escolhidos pelo usuário)."""
    p = _project(session, pid)
    _check_range(p, body.start_s, body.end_s)
    from ..services.templates import get_template
    from ..worker.tasks import template_overrides

    hook = _hook_for(pid, body.start_s, body.end_s)
    opts = options_of(p)
    c = Clip(project_id=pid, start_s=round(body.start_s, 3), end_s=round(body.end_s, 3), origin="manual",
             status="edited", title=body.title.strip() or (hook[:60] if hook else "Corte manual"), hook_text=hook,
             reframe_mode=opts.reframe_mode, caption_overrides_json=template_overrides(get_template(opts.template)))
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.get("/clips/{cid}", response_model=Clip)
def get_clip(cid: int, session: Session = Depends(get_session)) -> Clip:
    return _clip(session, cid)


@router.patch("/clips/{cid}", response_model=Clip)
def patch_clip(cid: int, body: ClipUpdate, session: Session = Depends(get_session)) -> Clip:
    c = _clip(session, cid)
    data = body.model_dump(exclude_unset=True)
    if "start_s" in data or "end_s" in data:
        start, end = data.get("start_s", c.start_s), data.get("end_s", c.end_s)
        _check_range(_project(session, c.project_id), start, end)
        if "hook_text" not in data:
            data["hook_text"] = _hook_for(c.project_id, start, end)
    for k, v in data.items():
        setattr(c, k, round(v, 3) if k in ("start_s", "end_s") else v)
    # qualquer edição de conteúdo tira o corte de "sugerido"/"renderizado" (o MP4 fica desatualizado)
    if c.status in ("suggested", "rendered", "error") and set(data) - {"status"}:
        c.status = "edited"
    c.updated_at = now()
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.post("/clips/{cid}/duplicate", response_model=Clip)
def duplicate_clip(cid: int, session: Session = Depends(get_session)) -> Clip:
    c = _clip(session, cid)
    data = c.model_dump(exclude={"id", "created_at", "updated_at", "output_path", "status", "origin", "post_json", "review_json"})
    dup = Clip(**data, status="edited", origin="manual")
    dup.title = f"{c.title} (cópia)"[:200]
    session.add(dup)
    session.commit()
    session.refresh(dup)
    return dup


@router.delete("/clips/{cid}")
def delete_clip(cid: int, session: Session = Depends(get_session)) -> dict:
    for j in session.exec(select(Job).where(col(Job.type).in_(CLIP_JOB_TYPES), Job.ref_id == cid)).all():
        session.delete(j)  # um render em andamento é interrompido pelo worker
    session.delete(_clip(session, cid))
    session.commit()
    return {"ok": True}


# --- Render -------------------------------------------------------------------
def _enqueue_render(session: Session, c: Clip) -> Job:
    job = active_job_for(session, "render", c.id)  # type: ignore[arg-type]
    return job or enqueue(session, "render", c.id)  # type: ignore[arg-type]


@router.post("/clips/{cid}/render", response_model=Job)
def render_clip(cid: int, session: Session = Depends(get_session)) -> Job:
    c = _clip(session, cid)
    if c.status == "discarded":
        raise HTTPException(409, "Restaure o corte antes de renderizar")
    return _enqueue_render(session, c)


@router.post("/projects/{pid}/render-all", response_model=list[Job])
def render_all(pid: int, only_pending: bool = True, session: Session = Depends(get_session)) -> list[Job]:
    """Renderiza os cortes não descartados (por padrão, só os que ainda não têm MP4 atualizado)."""
    _project(session, pid)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")
                         .order_by(col(Clip.score).desc())).all()
    todo = [c for c in clips if not (only_pending and c.status == "rendered" and c.output_path and Path(c.output_path).exists())]
    if not todo:
        raise HTTPException(409, "Todos os cortes já estão renderizados")
    jobs = [_enqueue_render(session, c) for c in todo]
    for j in jobs:
        session.refresh(j)  # commits seguidos expiram os anteriores (serializariam vazios)
    return jobs


@router.get("/clips/{cid}/file")
def clip_file(cid: int, download: bool = False, session: Session = Depends(get_session)) -> FileResponse:
    """MP4 final (com Range, para tocar no app; ?download=1 força o download)."""
    c = _clip(session, cid)
    path = Path(c.output_path) if c.output_path else None
    if not path or not path.is_file():
        raise HTTPException(404, "Este corte ainda não foi renderizado")
    return FileResponse(path, media_type="video/mp4", filename=path.name if download else None,
                        content_disposition_type="attachment" if download else "inline")


# --- Pacote para postar (textos + capa + .zip) ------------------------------------------
def _clip_dir(c: Clip) -> Path:
    return get_settings().project_dir(c.project_id) / "clips" / str(c.id)


def _enqueue_post_pack(session: Session, c: Clip, texts: bool, cover: bool) -> Job | None:
    if not (texts or cover):
        return None
    return active_job_for(session, "post_pack", c.id) or enqueue(  # type: ignore[arg-type]
        session, "post_pack", c.id, params={"texts": texts, "cover": cover})  # type: ignore[arg-type]


@router.post("/clips/{cid}/post-pack", response_model=Job)
def post_pack_clip(cid: int, body: PostPackRequest, session: Session = Depends(get_session)) -> Job:
    """(Re)gera os textos por plataforma e/ou a capa de um corte."""
    c = _clip(session, cid)
    if c.status == "discarded":
        raise HTTPException(409, "Restaure o corte antes de gerar o pacote")
    job = _enqueue_post_pack(session, c, body.texts, body.cover)
    if job is None:
        raise HTTPException(422, "Escolha textos e/ou capa")
    return job


@router.post("/projects/{pid}/post-pack", response_model=list[Job])
def post_pack_project(pid: int, body: PostPackRequest, session: Session = Depends(get_session)) -> list[Job]:
    """Pacote para todos os cortes ativos; com only_missing, só o que ainda falta (textos ou capa)."""
    from ..services import postpack

    _project(session, pid)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")
                         .order_by(col(Clip.score).desc())).all()
    jobs = []
    for c in clips:
        texts = body.texts and not (body.only_missing and postpack.has_texts(postpack.load_post(c.post_json)))
        cover = body.cover and not (body.only_missing and (_clip_dir(c) / "cover.jpg").exists())
        j = _enqueue_post_pack(session, c, texts, cover)
        if j:
            jobs.append(j)
    if not jobs:
        raise HTTPException(409, "Todos os cortes ativos já têm textos e capa")
    for j in jobs:
        session.refresh(j)
    return jobs


@router.put("/clips/{cid}/post", response_model=Clip)
def put_post_texts(cid: int, body: PostTexts, session: Session = Depends(get_session)) -> Clip:
    """Edição manual dos textos (não mexe no status do corte: o MP4 continua valendo)."""
    from ..services import postpack

    c = _clip(session, cid)
    data = body.model_dump()
    try:
        texts = postpack.normalize_post(data)
    except ValueError as e:
        raise HTTPException(422, "Preencha pelo menos uma legenda ou o título do Shorts") from e
    cur = postpack.load_post(c.post_json)
    cur.update(texts, edited_at=now().isoformat())
    c.post_json = json.dumps(cur, ensure_ascii=False)
    c.updated_at = now()
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.get("/clips/{cid}/cover")
def clip_cover(cid: int, titled: bool = False, download: bool = False, session: Session = Depends(get_session)) -> FileResponse:
    c = _clip(session, cid)
    path = _clip_dir(c) / ("cover-titulo.jpg" if titled else "cover.jpg")
    if not path.is_file():
        raise HTTPException(404, "A capa deste corte ainda não foi gerada")
    from ..services.renderer import slugify

    name = f"{slugify(c.title or 'corte')}{'-com-titulo' if titled else ''}.jpg"
    return FileResponse(path, media_type="image/jpeg", filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "no-cache"})


@router.get("/projects/{pid}/export.zip")
def export_zip(pid: int, session: Session = Depends(get_session)) -> FileResponse:
    """Exportar tudo: MP4s dos cortes ativos + capas + textos.csv + textos.txt."""
    from ..services import postpack
    from ..services.renderer import slugify

    p = _project(session, pid)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")
                         .order_by(col(Clip.score).desc(), col(Clip.start_s))).all()
    items, skipped, names = [], 0, set()
    for c in clips:
        mp4 = Path(c.output_path) if c.output_path else None
        if not mp4 or not mp4.is_file():
            skipped += 1
            continue
        name = mp4.name if mp4.name not in names else f"{mp4.stem}_{c.id}.mp4"
        names.add(name)
        cdir = _clip_dir(c)
        items.append(postpack.ExportItem(mp4=mp4, name=name, score=c.score, duration_s=c.end_s - c.start_s,
                                         title=c.title, post=postpack.load_post(c.post_json),
                                         cover=cdir / "cover.jpg", cover_title=cdir / "cover-titulo.jpg"))
    if not items:
        raise HTTPException(409, "Nenhum corte renderizado para exportar — renderize os cortes primeiro")
    tmp_dir = get_settings().data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / f"export-{pid}-{now().strftime('%Y%m%d%H%M%S%f')}.zip"
    postpack.build_zip(dest, items, p.name, skipped)
    return FileResponse(dest, media_type="application/zip", filename=f"{slugify(p.name, 60)}-cortes.zip",
                        background=BackgroundTask(dest.unlink, missing_ok=True))


# --- Revisão visual pelo Claude (paga) --------------------------------------------------
def _reviewable(c: Clip) -> bool:
    return c.status == "rendered" and bool(c.output_path) and Path(c.output_path).is_file()


def _review_current(c: Clip) -> bool:
    """Já existe revisão para ESTE render (re-render invalida)."""
    try:
        r = json.loads(c.review_json or "{}")
    except ValueError:
        return False
    return bool(r.get("verdict")) and r.get("rendered_at") == (c.rendered_at.isoformat() if c.rendered_at else None)


def _speech_chars(c: Clip) -> int:
    path = get_settings().project_dir(c.project_id) / "transcript.json"
    if not path.exists():
        return 0
    words = Words.from_transcript(json.loads(path.read_text(encoding="utf-8"))).w
    return sum(len(w["w"]) + 1 for w in words if w["s"] >= c.start_s - 0.05 and w["e"] <= c.end_s + 0.05) \
        + 8 * max(1, len(words) // 12)


def _claude_configured() -> bool:
    import os

    from ..config import load_user_settings

    return bool(load_user_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))


def _check_model(model: str, require_key: bool = False) -> None:
    from ..services import claude

    if model not in claude.PRICES:
        raise HTTPException(422, f"Modelo desconhecido: {model}")
    if require_key and not _claude_configured():
        raise HTTPException(409, "Configure a chave da Anthropic em Configurações (ou ANTHROPIC_API_KEY)")


@router.get("/projects/{pid}/review-estimate")
def review_estimate(pid: int, model: str = "claude-opus-5-5", only_missing: bool = True,
                    session: Session = Depends(get_session)) -> dict:
    """Custo estimado da revisão visual dos cortes renderizados (antes de confirmar)."""
    from ..services import claude, review

    _check_model(model)
    _project(session, pid)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")).all()
    todo = [c for c in clips if _reviewable(c) and not (only_missing and _review_current(c))]
    per = [claude.estimate_review(model, review.N_FRAMES, _speech_chars(c)) for c in todo]
    return {"model": model, "clips": len(todo), "clip_ids": [c.id for c in todo],
            "usd": round(sum(e["usd"] for e in per), 4), "per_clip_usd": [e["usd"] for e in per],
            "input_tokens": sum(e["input_tokens"] for e in per), "output_tokens": sum(e["output_tokens"] for e in per),
            "prices_as_of": claude.PRICES_AS_OF, "configured": _claude_configured()}


@router.get("/clips/{cid}/review-estimate")
def clip_review_estimate(cid: int, model: str = "claude-opus-5-5", session: Session = Depends(get_session)) -> dict:
    from ..services import claude, review

    _check_model(model)
    return {**claude.estimate_review(model, review.N_FRAMES, _speech_chars(_clip(session, cid))),
            "configured": _claude_configured()}


def _enqueue_review(session: Session, c: Clip, model: str) -> Job:
    return active_job_for(session, "review", c.id) or enqueue(  # type: ignore[arg-type]
        session, "review", c.id, params={"model": model})  # type: ignore[arg-type]


@router.post("/clips/{cid}/review", response_model=Job)
def review_clip(cid: int, body: ReviewRequest, session: Session = Depends(get_session)) -> Job:
    _check_model(body.model, require_key=True)
    c = _clip(session, cid)
    if not _reviewable(c):
        raise HTTPException(409, "Renderize o corte antes de revisar")
    return _enqueue_review(session, c, body.model)


@router.put("/clips/{cid}/review", response_model=Clip)
def submit_review(cid: int, body: ReviewSubmit, session: Session = Depends(get_session)) -> Clip:
    """Grava uma revisão feita pelo Claude Code (plano Pro do usuário) — sem custo na API, não entra em ai_cost_json."""
    from ..services import review

    c = _clip(session, cid)
    if not _reviewable(c):
        raise HTTPException(409, "Renderize o corte antes de revisar")
    result = review.parse(json.dumps(body.model_dump()))
    data = {**result, "model": body.model[:80], "at": now().isoformat(),
            "cost": {"provider": "claude-code", "usd": 0, "tokens_approx": body.tokens_approx},
            "rendered_at": c.rendered_at.isoformat() if c.rendered_at else None}
    c.review_json = json.dumps(data, ensure_ascii=False)
    c.updated_at = now()
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.post("/projects/{pid}/review", response_model=list[Job])
def review_project(pid: int, body: ReviewRequest, session: Session = Depends(get_session)) -> list[Job]:
    _check_model(body.model, require_key=True)
    _project(session, pid)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")
                         .order_by(col(Clip.score).desc())).all()
    jobs = [_enqueue_review(session, c, body.model) for c in clips
            if _reviewable(c) and not (body.only_missing and _review_current(c))]
    if not jobs:
        raise HTTPException(409, "Nenhum corte renderizado para revisar (ou todos já revisados)")
    for j in jobs:
        session.refresh(j)
    return jobs


# --- Estilos de legenda ------------------------------------------------------------
@router.get("/caption-styles", response_model=list[CaptionStyle])
def list_styles(session: Session = Depends(get_session)) -> list[CaptionStyle]:
    return list(session.exec(select(CaptionStyle).order_by(col(CaptionStyle.is_builtin).desc(), col(CaptionStyle.id))).all())


@router.post("/caption-styles", response_model=CaptionStyle)
def create_style(body: CaptionStyleIn, session: Session = Depends(get_session)) -> CaptionStyle:
    st = CaptionStyle(**body.model_dump(), is_builtin=False)
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


@router.patch("/caption-styles/{sid}", response_model=CaptionStyle)
def patch_style(sid: int, body: CaptionStyleUpdate, session: Session = Depends(get_session)) -> CaptionStyle:
    st = session.get(CaptionStyle, sid)
    if st is None:
        raise HTTPException(404, "Estilo não encontrado")
    if st.is_builtin:
        raise HTTPException(409, "Presets embutidos não podem ser alterados; salve como novo preset")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(st, k, v)
    st.updated_at = now()
    session.add(st)
    session.commit()
    session.refresh(st)
    return st


@router.delete("/caption-styles/{sid}")
def delete_style(sid: int, session: Session = Depends(get_session)) -> dict:
    st = session.get(CaptionStyle, sid)
    if st is None:
        raise HTTPException(404, "Estilo não encontrado")
    if st.is_builtin:
        raise HTTPException(409, "Presets embutidos não podem ser apagados")
    for c in session.exec(select(Clip).where(Clip.caption_style_id == sid)).all():
        c.caption_style_id = None
        session.add(c)
    session.delete(st)
    session.commit()
    return {"ok": True}


@router.get("/clips/{cid}/crop-track")
def crop_track(cid: int, fps: float = 10, session: Session = Depends(get_session)) -> dict:
    """Trilha de crop calculada (preview no editor). Usa a pré-análise de cenas/rostos do projeto."""
    from ..services import reframer

    c = _clip(session, cid)
    p = _project(session, c.project_id)
    if not p.width or not p.height:
        raise HTTPException(409, "O vídeo do projeto ainda não foi preparado")
    pdir = get_settings().project_dir(p.id)  # type: ignore[arg-type]
    mode = c.reframe_mode if c.reframe_mode in ("auto", "speaker", "split", "gameplay", "manual", "center") else "center"
    keyframes = []
    if mode == "manual":
        try:
            keyframes = [k for k in json.loads(c.manual_crop_json or "[]") if "t" in k and "x" in k]
        except ValueError:
            keyframes = []
        if not keyframes:
            mode = "center"
    faces, cuts = {}, []
    if mode in ("auto", "speaker", "split", "gameplay"):
        fp, sp = pdir / "faces.json", pdir / "scenes.json"
        if not (fp.exists() and sp.exists()):
            raise HTTPException(409, "A análise de rostos deste projeto ainda não terminou")
        faces, cuts = json.loads(fp.read_text()), json.loads(sp.read_text())["cuts"]
    fps = max(1.0, min(60.0, fps))
    speech = None
    if mode == "speaker":
        from ..worker.tasks import speech_intervals

        tp = pdir / "transcript.json"
        words = [w for seg in json.loads(tp.read_text())["segments"] for w in seg["words"]] if tp.exists() else []
        speech = speech_intervals(words)
    try:
        layout = json.loads(c.layout_json or "{}")
    except ValueError:
        layout = {}
    return reframer.compute_track(faces, cuts, c.start_s, c.end_s, p.width, p.height, fps, mode, keyframes,
                                  speech=speech, layout=layout).to_json()


@router.get("/templates")
def list_templates() -> list[dict]:
    from ..services.templates import TEMPLATES

    return [t.to_json() for t in TEMPLATES.values()]


@router.post("/projects/{pid}/apply-template")
def apply_template(pid: int, body: ApplyTemplate, session: Session = Depends(get_session)) -> dict:
    """Aplica um template (enquadramento + posição da legenda) a todos os cortes ativos do projeto e passa a
    ser o padrão do projeto. Com render=true, já enfileira o render de todos."""
    from ..services.templates import TEMPLATES
    from ..worker.tasks import template_overrides

    if body.template not in TEMPLATES:
        raise HTTPException(422, "Template desconhecido")
    t = TEMPLATES[body.template]
    p = _project(session, pid)
    opts = options_of(p)
    opts.template, opts.reframe_mode = t.key, t.reframe_mode  # type: ignore[assignment]
    p.settings_json = opts.model_dump_json()
    p.updated_at = now()
    session.add(p)
    clips = session.exec(select(Clip).where(Clip.project_id == pid, Clip.status != "discarded")).all()
    for c in clips:
        changed = c.reframe_mode != t.reframe_mode
        c.reframe_mode = t.reframe_mode
        new_ov = template_overrides(t, c.caption_overrides_json)
        changed |= new_ov != c.caption_overrides_json
        c.caption_overrides_json = new_ov
        if changed and c.status in ("rendered", "suggested", "error"):
            c.status = "edited"
        c.updated_at = now()
        session.add(c)
    session.commit()
    jobs = []
    if body.render:
        for c in clips:
            session.refresh(c)
            jobs.append(_enqueue_render(session, c))
    return {"ok": True, "clips": len(clips), "renders": len(jobs)}
