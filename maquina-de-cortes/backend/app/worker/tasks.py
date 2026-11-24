"""Handlers por tipo de job. Cada handler recebe um JobContext."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Session, col, select

from ..config import get_settings, load_user_settings
from ..db import engine
from ..errors import friendly
from ..models import Clip, Download, Job, Project, now
from ..project_ops import ProjectError, options_of, project_from_download, start_analysis
from ..queue import enqueue
from ..services import captions, downloader, hardware, highlighter, probe, proxy, reframer, renderer, transcriber
from ..services.caption_styles import style_for_clip
from ..services.templates import get_template
from ..services.ffmpeg import FFmpegCanceled, run_ffmpeg

log = logging.getLogger("worker.tasks")


class JobCanceled(Exception):
    pass


class JobContext:
    """Interface do handler com a fila: progresso, cancelamento e subprocessos."""

    REPORT_INTERVAL_S = 0.5

    def __init__(self, job: Job) -> None:
        self.job_id: int = job.id  # type: ignore[assignment]
        self.ref_id = job.ref_id
        self.type = job.type
        self.cancel_event = threading.Event()
        self.interrupted = False  # True = worker encerrando (job volta para a fila, não é "cancelado")
        self._procs: list[subprocess.Popen] = []
        self._last_report = 0.0
        self._lock = threading.Lock()

    # --- progresso -----------------------------------------------------------
    def report(self, progress: float | None = None, message: str | None = None, force: bool = False) -> None:
        t = time.monotonic()
        if not force and t - self._last_report < self.REPORT_INTERVAL_S:
            return
        self._last_report = t
        values: dict = {"updated_at": now()}
        if progress is not None:
            values["progress"] = round(max(0.0, min(100.0, progress)), 1)
        if message is not None:
            values["message"] = message
        with Session(engine) as s:
            s.exec(update(Job).where(col(Job.id) == self.job_id, col(Job.status) == "running").values(**values))  # type: ignore[call-overload]
            s.commit()

    # --- cancelamento --------------------------------------------------------
    def is_canceled(self) -> bool:
        return self.cancel_event.is_set()

    def check_canceled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCanceled()

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            for p in self._procs:
                if p.poll() is None:
                    p.terminate()

    def register_process(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.append(p)
        if self.cancel_event.is_set():
            p.terminate()


# ---------------------------------------------------------------------------
def _update_download(dl_id: int, **values) -> None:
    values["updated_at"] = now()
    with Session(engine) as s:
        s.exec(update(Download).where(col(Download.id) == dl_id).values(**values))  # type: ignore[call-overload]
        s.commit()


def handle_download(ctx: JobContext) -> None:
    with Session(engine) as s:
        dl = s.get(Download, ctx.ref_id)
        if dl is None:
            raise downloader.FriendlyError("Download não existe mais.")
        url, fmt = dl.url, dl.format_choice
    _update_download(ctx.ref_id, status="downloading", progress=0, error="", error_detail="")
    ctx.report(0, "Conectando…", force=True)

    last = {"t": 0.0}

    def on_progress(p: downloader.Progress) -> None:
        t = time.monotonic()
        if t - last["t"] < 0.5 and p.phase == "download":
            return
        last["t"] = t
        if p.phase == "postprocess":
            msg = "Convertendo para MP3…" if fmt == "audio_mp3" else "Juntando áudio e vídeo…"
        else:
            msg = f"Baixando {p.percent:.0f}%" + (f" · {p.speed}" if p.speed else "") + (f" · ETA {p.eta}" if p.eta else "")
        _update_download(ctx.ref_id, progress=round(p.percent, 1), speed=p.speed, eta=p.eta)
        ctx.report(p.percent, msg, force=True)

    def on_info(info: dict) -> None:
        fields = {k: v for k, v in downloader.info_fields(info).items() if v}
        if fields:
            _update_download(ctx.ref_id, **fields)

    out_dir = get_settings().data_dir / "downloads"
    try:
        path = downloader.download(url, fmt, out_dir, on_progress, ctx.is_canceled, on_info,
                                   cookies_path=load_user_settings().cookies_path)
    except downloader.Canceled:
        _update_download(ctx.ref_id, status="canceled", speed="", eta="")
        raise JobCanceled() from None
    except downloader.FriendlyError as e:
        _update_download(ctx.ref_id, status="error", error=str(e), error_detail=e.detail, speed="", eta="")
        raise

    _update_download(ctx.ref_id, status="done", progress=100, speed="", eta="",
                     file_path=str(path), filesize=path.stat().st_size)
    ctx.report(100, "Concluído", force=True)

    with Session(engine) as s:
        dl = s.get(Download, ctx.ref_id)
        if dl and dl.send_to_project and not dl.project_id:
            try:
                p = project_from_download(s, dl, load_user_settings().default_language)
                start_analysis(s, p)
                log.info("download %s → projeto %s (análise enfileirada)", dl.id, p.id)
            except ProjectError as e:
                log.warning("download %s não virou projeto: %s", dl.id, e)


# ---------------------------------------------------------------------------
# Projetos: probe + proxy + áudio + forma de onda + thumbnails → transcrição
# ---------------------------------------------------------------------------
def _update_project(pid: int, **values) -> None:
    values["updated_at"] = now()
    with Session(engine) as s:
        s.exec(update(Project).where(col(Project.id) == pid).values(**values))  # type: ignore[call-overload]
        s.commit()


def _load_project(pid: int) -> Project:
    with Session(engine) as s:
        p = s.get(Project, pid)
        if p is None:
            raise RuntimeError("Projeto não existe mais.")
        s.expunge(p)
        return p


def _source_signature(path: Path) -> str:
    st = path.stat()
    return f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"


def _project_guard(ctx: "JobContext", stage: str):
    """Context manager: marca etapa; em erro/cancelamento reflete no projeto."""

    @contextmanager
    def guard():
        _update_project(ctx.ref_id, status="processing", stage=stage, progress=0, error="", error_detail="")
        try:
            yield
        except (JobCanceled, FFmpegCanceled, InterruptedError):
            if not ctx.interrupted:
                _update_project(ctx.ref_id, status="new", progress=0, error="Análise cancelada")
            raise JobCanceled() from None
        except Exception as e:
            if ctx.is_canceled() and not ctx.interrupted:
                _update_project(ctx.ref_id, status="new", progress=0, error="Análise cancelada")
                raise JobCanceled() from None
            if not ctx.interrupted:
                msg, detail = friendly(e)
                _update_project(ctx.ref_id, status="error", error=msg, error_detail=detail[-4000:])
            raise

    return guard()


def handle_probe_proxy(ctx: JobContext) -> None:
    p = _load_project(ctx.ref_id)
    pdir = get_settings().project_dir(ctx.ref_id)
    pdir.mkdir(parents=True, exist_ok=True)
    src = Path(p.source_path)

    with _project_guard(ctx, "probe"):
        if not src.is_file():
            raise RuntimeError(f"Arquivo-fonte não encontrado: {src}")
        ctx.report(0, "Lendo informações do vídeo…", force=True)
        info = probe.probe(src)
        if not info.has_video:
            raise probe.ProbeError("O arquivo não tem vídeo (só áudio).")
        _update_project(ctx.ref_id, duration_s=info.duration_s, width=info.width, height=info.height,
                        fps=info.fps, has_audio=info.has_audio)
        if not info.has_audio:
            raise probe.ProbeError("O vídeo não tem áudio — não há o que transcrever.")

        meta_path = pdir / "meta.json"
        sig = _source_signature(src)
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        same_source = meta.get("source_signature") == sig
        files = {k: pdir / k for k in ("proxy.mp4", "audio.wav", "waveform.json")}
        thumbs = pdir / "thumbs"
        if not same_source:
            # fonte nova/alterada: tudo que foi derivado dela deixa de valer
            for stale in ("proxy.mp4", "audio.wav", "waveform.json", "scenes.json", "faces.json"):
                (pdir / stale).unlink(missing_ok=True)
            if thumbs.exists():
                shutil.rmtree(thumbs)
            _update_project(ctx.ref_id, faces_ready=False)
        # cada etapa só roda se o arquivo dela faltar (cache por arquivo; a limpeza de disco apaga só alguns)
        need_audio = not files["audio.wav"].exists()
        need_wave = need_audio or not files["waveform.json"].exists()
        need_proxy = not files["proxy.mp4"].exists()
        need_thumbs = not thumbs.is_dir() or not any(thumbs.glob("*.jpg"))  # mesma fonte = mesmas miniaturas
        if not (need_audio or need_wave or need_proxy or need_thumbs):
            ctx.report(100, "Arquivos já preparados (cache)", force=True)
        else:
            us = load_user_settings()
            encoder = "nvenc" if (us.encoder == "nvenc" or (us.encoder == "auto" and hardware.nvenc_works())) else "x264"
            weights = [(k, w) for k, w, need in (("audio", 15, need_audio), ("proxy", 70, need_proxy),
                                                  ("thumbs", 15, need_thumbs)) if need]
            step = proxy.staged(weights or [("audio", 1)],
                                lambda pct, msg: (ctx.report(pct, msg), _update_project(ctx.ref_id, progress=round(pct, 1))))
            common = {"register_process": ctx.register_process, "is_canceled": ctx.is_canceled, "duration_s": info.duration_s}
            _update_project(ctx.ref_id, stage="proxy")

            if need_audio:
                tmp_wav = pdir / "audio.tmp.wav"
                proxy_run(proxy.audio_args(src, tmp_wav), step("audio", "Extraindo áudio…"), common, "Falha ao extrair o áudio")
                tmp_wav.replace(files["audio.wav"])
                ctx.check_canceled()
            if need_wave:
                proxy.compute_peaks(files["audio.wav"], files["waveform.json"])

            if need_proxy:
                tmp_proxy = pdir / "proxy.tmp.mp4"
                try:
                    proxy_run(proxy.proxy_args(src, tmp_proxy, info.fps, encoder, True), step("proxy", "Gerando proxy 540p…"),
                              common, "Falha ao gerar o proxy")
                except Exception:
                    if encoder != "nvenc" or ctx.is_canceled():
                        raise
                    log.warning("proxy com NVENC falhou; tentando libx264")
                    proxy_run(proxy.proxy_args(src, tmp_proxy, info.fps, "x264", True), step("proxy", "Gerando proxy 540p…"),
                              common, "Falha ao gerar o proxy")
                tmp_proxy.replace(files["proxy.mp4"])

            if need_thumbs:
                if thumbs.exists():
                    for f in thumbs.glob("*.jpg"):
                        f.unlink()
                thumbs.mkdir(exist_ok=True)
                proxy_run(proxy.thumbs_args(files["proxy.mp4"], thumbs), step("thumbs", "Gerando miniaturas…"),
                          common, "Falha ao gerar miniaturas")
            meta_path.write_text(json.dumps({"source_signature": sig, "probe": info.to_dict()}))

    need_faces = not ((pdir / "faces.json").exists() and (pdir / "scenes.json").exists())
    with Session(engine) as s:
        if p.prepare_only:
            # "Preparar de novo" (arquivos limpos): só restaura os arquivos; não refaz transcrição/análise
            if need_faces:
                enqueue(s, "reframe", ctx.ref_id)
        else:
            enqueue(s, "transcribe", ctx.ref_id, priority=1)
            if need_faces:
                enqueue(s, "reframe", ctx.ref_id)  # CPU, em paralelo com a transcrição
    if p.prepare_only:
        _update_project(ctx.ref_id, status="ready", stage="done", progress=100, prepare_only=False)
        ctx.report(100, "Arquivos restaurados", force=True)
        return
    _update_project(ctx.ref_id, stage="transcribe", progress=0)
    ctx.report(100, "Vídeo preparado", force=True)


def proxy_run(args: list[str], on_pct, common: dict, msg: str) -> None:
    run_ffmpeg(args, on_progress=on_pct, error_message=msg, **common)


def handle_transcribe(ctx: JobContext) -> None:
    p = _load_project(ctx.ref_id)
    pdir = get_settings().project_dir(ctx.ref_id)
    audio = pdir / "audio.wav"
    out = pdir / "transcript.json"
    opts = options_of(p)
    lang = None if opts.language in ("", "auto") else opts.language

    with _project_guard(ctx, "transcribe"):
        if not audio.exists():
            raise RuntimeError("audio.wav não existe — rode a preparação do vídeo de novo.")
        us = load_user_settings()
        cached = None
        if out.exists():
            try:
                cached = json.loads(out.read_text(encoding="utf-8"))
            except ValueError:
                cached = None
        if cached and cached.get("requested_language", "auto") == (lang or "auto") and not cached.get("partial"):
            result = cached
            ctx.report(100, "Transcrição já existe (cache)", force=True)
        else:
            last = {"t": 0.0}

            def on_prog(pct: float, msg: str) -> None:
                ctx.report(pct, msg)
                t = time.monotonic()
                if t - last["t"] >= 1:
                    last["t"] = t
                    _update_project(ctx.ref_id, progress=round(pct, 1))

            result = transcriber.transcribe(audio, out, p.duration_s or 0, lang, us, on_prog, ctx.is_canceled)
            result["requested_language"] = lang or "auto"
            out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    words = sum(len(s["words"]) for s in result["segments"])
    _update_project(ctx.ref_id, stage="analyze", progress=0,
                    detected_language=result.get("language", ""), word_count=words)
    with Session(engine) as s:
        enqueue(s, "analyze", ctx.ref_id, priority=1)
    ctx.report(100, f"Transcrição pronta · {words} palavras", force=True)


def template_overrides(template, current: str = "{}") -> str:
    """caption_overrides_json com a posição/tamanho da legenda do template (preserva correções de palavras)."""
    ov = captions.parse_overrides(current)
    style = dict(ov.style)
    if template.caption_position_y is not None:
        style["position_y"] = template.caption_position_y
    else:
        style.pop("position_y", None)
    if template.caption_font_size is not None:
        style["font_size"] = template.caption_font_size
    else:
        style.pop("font_size", None)
    data: dict = {"words": ov.words, "style": style}
    if ov.title_until:
        data["title_until"] = ov.title_until
    return json.dumps(data, ensure_ascii=False)


def speech_intervals(words: list[dict], gap: float = 0.4) -> list[tuple[float, float]]:
    """Intervalos com fala (palavras unidas se o silêncio entre elas for < gap)."""
    out: list[tuple[float, float]] = []
    for w in sorted(words, key=lambda x: x["s"]):
        if out and w["s"] - out[-1][1] < gap:
            out[-1] = (out[-1][0], max(out[-1][1], w["e"]))
        else:
            out.append((w["s"], w["e"]))
    return out


def handle_analyze(ctx: JobContext) -> None:
    p = _load_project(ctx.ref_id)
    pdir = get_settings().project_dir(ctx.ref_id)
    opts = options_of(p)
    us = load_user_settings()

    with _project_guard(ctx, "analyze"):
        tpath = pdir / "transcript.json"
        if not tpath.exists():
            raise RuntimeError("Transcrição não existe — rode a análise de novo.")
        transcript = json.loads(tpath.read_text(encoding="utf-8"))

        # VRAM: Whisper large-v3 (~3,7 GB) + qwen2.5:7b (~4,6 GB) não cabem juntos numa GPU < 10 GB
        _gpu, vram = hardware.nvidia_gpu()
        if vram is None or vram < 10_000:
            transcriber.release_model()

        state = {"win": 0, "n": 1}

        def on_window(i: int, n: int) -> None:
            state["win"], state["n"] = i, n
            pct = 100 * i / n
            ctx.report(pct, f"IA lendo o trecho {i + 1} de {n}…", force=True)
            _update_project(ctx.ref_id, progress=round(pct, 1))

        def on_chunk(tokens: int) -> None:
            # progresso dentro da janela (estimativa: ~120 tokens por candidato pedido)
            frac = min(0.95, tokens / 900)
            pct = 100 * (state["win"] + frac) / state["n"]
            ctx.report(pct, f"IA lendo o trecho {state['win'] + 1} de {state['n']}…")

        llm = highlighter.ollama_chat(us.ollama_url, us.ollama_model, ctx.is_canceled, on_chunk)
        try:
            template = get_template(opts.template)
            clips = highlighter.find_highlights(
                transcript, p.duration_s or 0, opts.num_clips, opts.min_s, opts.max_s, opts.extra_prompt,
                llm, pdir / "audio.wav", on_window, ctx.is_canceled, template=template,
            )
        except highlighter.Canceled:
            raise JobCanceled() from None

        with Session(engine) as s:
            # reanálise: substitui sugestões da IA; mantém cortes editados, renderizados e manuais
            for old in s.exec(select(Clip).where(Clip.project_id == ctx.ref_id, Clip.origin == "ai",
                                                 col(Clip.status).in_(["suggested", "discarded"]))).all():
                s.delete(old)
            overrides = template_overrides(template)
            for c in clips:
                s.add(Clip(project_id=ctx.ref_id, title=c["title"], hook_text=c["hook_text"], reason=c["reason"],
                           start_s=c["start_s"], end_s=c["end_s"], score=c["score"],
                           score_breakdown_json=json.dumps(c["breakdown"], ensure_ascii=False),
                           reframe_mode=opts.reframe_mode, caption_overrides_json=overrides))
            s.commit()

    _update_project(ctx.ref_id, status="ready", stage="done", progress=100)
    ctx.report(100, f"{len(clips)} corte(s) sugerido(s)", force=True)


# ---------------------------------------------------------------------------
# Reenquadramento: pré-análise de cenas + rostos (Fase 5)
# ---------------------------------------------------------------------------
def ensure_face_analysis(project: Project, report: Callable[[float, str], None], ctx: JobContext) -> tuple[dict, list[float]]:
    pdir = get_settings().project_dir(project.id)  # type: ignore[arg-type]
    proxy_path = pdir / "proxy.mp4"
    if not proxy_path.exists():
        raise RuntimeError("O vídeo do projeto ainda não foi preparado.")
    aspect = (project.width or 16) / (project.height or 9)
    try:
        faces, cuts = reframer.analyze_project(proxy_path, project.duration_s or 0, pdir, report, ctx.is_canceled,
                                               ctx.register_process, aspect)
    except reframer.ReframeCanceled:
        raise JobCanceled() from None
    _update_project(project.id, faces_ready=True)  # type: ignore[arg-type]
    return faces, cuts


def handle_reframe(ctx: JobContext) -> None:
    p = _load_project(ctx.ref_id)
    faces, cuts = ensure_face_analysis(p, lambda pct, msg: ctx.report(pct, msg), ctx)
    with_face = sum(1 for f in faces["frames"] if f)
    ctx.report(100, f"{len(cuts)} troca(s) de câmera · rosto em {100 * with_face / max(1, len(faces['frames'])):.0f}% do vídeo",
               force=True)


# ---------------------------------------------------------------------------
# Render (Fase 4)
# ---------------------------------------------------------------------------
def _update_clip(cid: int, **values) -> None:
    values["updated_at"] = now()
    with Session(engine) as s:
        s.exec(update(Clip).where(col(Clip.id) == cid).values(**values))  # type: ignore[call-overload]
        s.commit()


def _parse_export(raw: str) -> tuple[str, bool | None]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    q = data.get("quality") if isinstance(data, dict) else None
    na = data.get("normalize_audio") if isinstance(data, dict) else None
    return (q if q in renderer.QUALITY else "normal"), (na if isinstance(na, bool) else None)


def export_dir_for(project: Project) -> Path:
    us = load_user_settings()
    base = Path(us.export_dir).expanduser() if us.export_dir.strip() else get_settings().data_dir / "exports"
    return base / f"{renderer.slugify(project.name, 60)}-{project.id}"


def handle_render(ctx: JobContext) -> None:
    with Session(engine) as s:
        clip = s.get(Clip, ctx.ref_id)
        if clip is None:
            raise RuntimeError("Corte não existe mais.")
        project = s.get(Project, clip.project_id)
        if project is None:
            raise RuntimeError("Projeto não existe mais.")
        style = style_for_clip(s, clip.caption_style_id, options_of(project).caption_style)
        ov = captions.parse_overrides(clip.caption_overrides_json)
        st = captions.Style.from_obj(style).merged(ov.style)
        for obj in (clip, project):
            s.expunge(obj)

    prev_status = clip.status if clip.status != "rendering" else "edited"
    _update_clip(clip.id, status="rendering", error="")  # type: ignore[arg-type]
    try:
        pdir = get_settings().project_dir(project.id)  # type: ignore[arg-type]
        cdir = pdir / "clips" / str(clip.id)
        cdir.mkdir(parents=True, exist_ok=True)
        transcript = json.loads((pdir / "transcript.json").read_text(encoding="utf-8")) \
            if (pdir / "transcript.json").exists() else {"segments": []}
        all_words = [w for seg in transcript["segments"] for w in seg["words"]]
        words = captions.clip_words(all_words, clip.start_s, clip.end_s, ov.words)
        dur = clip.end_s - clip.start_s
        ass = captions.build_ass(words, st, dur, title=clip.title_overlay, title_until=ov.title_until)
        (cdir / "captions.ass").write_text(ass, encoding="utf-8")

        src = Path(project.source_path)
        if not src.is_file():
            raise RuntimeError(f"Arquivo-fonte não encontrado: {src}")
        mode = clip.reframe_mode
        keyframes = []
        if mode == "manual":
            try:
                keyframes = [k for k in json.loads(clip.manual_crop_json or "[]") if "t" in k and "x" in k]
            except ValueError:
                keyframes = []
            if not keyframes:
                mode = "center"  # manual sem keyframes = centro
        us = load_user_settings()
        encoder = "nvenc" if (us.encoder == "nvenc" or (us.encoder == "auto" and hardware.nvenc_works())) else "x264"
        quality, normalize = _parse_export(clip.export_json)
        spec = renderer.RenderSpec(source=src, start_s=clip.start_s, end_s=clip.end_s, src_w=project.width or 1920,
                                   src_h=project.height or 1080, src_fps=project.fps, mode=mode, encoder=encoder,
                                   normalize_audio=us.normalize_audio if normalize is None else normalize,
                                   has_audio=project.has_audio, quality=quality)

        track = None
        wide = (project.width or 0) / max(1, project.height or 1) > 9 / 16 + 0.01
        if mode in ("auto", "speaker", "split", "manual", "gameplay") and wide:
            faces, cuts = ({}, []) if mode == "manual" else ensure_face_analysis(
                project, lambda pct, msg: ctx.report(min(40.0, 0.4 * pct), f"Analisando rostos (1ª vez)… {msg}"), ctx)
            try:
                layout = json.loads(clip.layout_json or "{}")
            except ValueError:
                layout = {}
            computed = reframer.compute_track(faces, cuts, clip.start_s, clip.end_s, spec.src_w, spec.src_h, spec.fps,
                                              mode, keyframes, speech=speech_intervals(all_words) if mode == "speaker" else None,
                                              layout=layout)
            (cdir / "crop.json").write_text(json.dumps(computed.to_json(), separators=(",", ":")))
            if mode == "gameplay":
                spec.gameplay = computed.gameplay  # caixas fixas: só filtros do ffmpeg
            else:
                track = computed
        elif mode not in ("center", "blur_fit"):
            mode = "center"  # fonte já vertical: não há o que reenquadrar
        spec.mode = mode if mode in ("center", "blur_fit", "gameplay") else "center"

        out_dir = export_dir_for(project)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / renderer.output_name(clip.score, clip.title or "corte")
        if out.exists() and str(out) != clip.output_path:
            out = out.with_name(f"{out.stem}_{clip.id}.mp4")  # outro corte já usa esse nome

        # cache: mesmo conteúdo (spec + legenda + fonte) → não renderiza de novo
        key = hashlib.sha256(json.dumps({
            "spec": {k: str(v) for k, v in spec.__dict__.items() if k != "encoder"},
            "ass": ass, "src": _source_signature(src), "v": renderer.RENDER_VERSION, "mode": mode,
            "track": hashlib.sha256(json.dumps(track.to_json()).encode()).hexdigest() if track else None,
        }, sort_keys=True).encode()).hexdigest()
        meta_path = cdir / "render.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        old_out = Path(clip.output_path) if clip.output_path else None
        if meta.get("hash") == key and old_out and old_out.exists():
            if old_out != out:
                old_out.replace(out)
            ctx.report(100, "Sem mudanças desde o último render (cache)", force=True)
        else:
            tmp = cdir / "render.tmp.mp4"

            def run(enc: str) -> None:
                spec.encoder = enc
                label = {"auto": "seguindo o rosto", "speaker": "quem fala no centro", "split": "tela dividida",
                         "gameplay": "webcam + jogo", "manual": "enquadramento manual"}.get(mode, "")
                ctx.report(0, f"Renderizando ({'NVENC' if enc == 'nvenc' else 'x264'}{', ' + label if label else ''})…", force=True)
                if track is not None:
                    try:
                        reframer.render_piped(src, clip.start_s, clip.end_s, track, renderer.piped_encode_args(spec), tmp,
                                              cdir, lambda pct: ctx.report(min(98.0, pct), f"Renderizando… {pct:.0f}%"),
                                              ctx.is_canceled, ctx.register_process)
                    except reframer.ReframeCanceled:
                        raise JobCanceled() from None
                    return
                run_ffmpeg(renderer.build_command(spec, tmp), duration_s=dur,
                           on_progress=lambda pct: ctx.report(min(98.0, pct), f"Renderizando… {pct:.0f}%"),
                           register_process=ctx.register_process, is_canceled=ctx.is_canceled, cwd=cdir,
                           error_message="Falha ao renderizar o corte")

            try:
                run(encoder)
            except Exception:
                if encoder != "nvenc" or ctx.is_canceled():
                    raise
                log.warning("render com NVENC falhou; tentando libx264")
                run("x264")
            shutil.move(str(tmp), out)
            meta_path.write_text(json.dumps({"hash": key, "encoder": spec.encoder, "mode": mode}))
            if old_out and old_out != out and old_out.exists() and old_out.parent == out_dir:
                old_out.unlink()  # título/nota mudou → apaga o arquivo antigo deste corte

        ctx.report(99, "Gerando miniatura…", force=True)
        try:
            run_ffmpeg(renderer.preview_args(out, dur / 2, cdir / "preview.jpg"), error_message="Falha na miniatura")
        except Exception:  # noqa: BLE001
            log.warning("miniatura do corte %s falhou", clip.id)
    except BaseException as e:
        if isinstance(e, (JobCanceled, FFmpegCanceled)) or ctx.is_canceled():
            _update_clip(clip.id, status=prev_status)  # type: ignore[arg-type]
            raise JobCanceled() from None
        if not ctx.interrupted:
            _update_clip(clip.id, status="error", error=friendly(e)[0])  # type: ignore[arg-type]
        else:
            _update_clip(clip.id, status=prev_status)  # type: ignore[arg-type]
        raise

    _update_clip(clip.id, status="rendered", output_path=str(out), rendered_at=now(), error="")  # type: ignore[arg-type]
    ctx.report(100, f"Pronto: {out.name}", force=True)


HANDLERS: dict[str, Callable[[JobContext], None]] = {
    "download": handle_download,
    "probe_proxy": handle_probe_proxy,
    "transcribe": handle_transcribe,
    "analyze": handle_analyze,
    "render": handle_render,
    "reframe": handle_reframe,
}
