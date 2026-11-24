"""Fase 1: fila, worker, SSE e downloader (sem internet: servidor HTTP local)."""

from __future__ import annotations

import functools
import http.server
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine, init_db
from app.events import EPOCH, Broker
from app.main import app
from app.models import Download, Job
from app.queue import cancel_job, claim, enqueue, recover_interrupted, retry_job
from app.services import downloader
from app.worker import runner, tasks

init_db()


# --- utilitários ---------------------------------------------------------------
@pytest.fixture(scope="module")
def media_server(tmp_path_factory):
    """Serve um MP4 curto gerado pelo ffmpeg em http://127.0.0.1:<porta>/."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg ausente")
    root = tmp_path_factory.mktemp("www")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(root / "clipe teste.mp4")],
        check=True,
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _new_download(url: str, fmt: str = "best") -> tuple[int, int]:
    with Session(engine) as s:
        dl = Download(url=url, format_choice=fmt)
        s.add(dl)
        s.commit()
        s.refresh(dl)
        job = enqueue(s, "download", dl.id)
        return dl.id, job.id  # type: ignore[return-value]


def _run_job(job_id: int) -> Job:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job is not None
        # simula o claim do worker
        job.status = "running"
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)
    runner._execute(ctx)
    with Session(engine) as s:
        return s.get(Job, job_id)  # type: ignore[return-value]


# --- downloader ---------------------------------------------------------------
def test_friendly_errors():
    assert "privado" in str(downloader.friendly_error(Exception("ERROR: Private video. Sign in")))
    assert "idade" in str(downloader.friendly_error(Exception("Sign in to confirm your age")))
    assert "região" in str(downloader.friendly_error(Exception("not available in your country")))
    assert "FFmpeg" in str(downloader.friendly_error(Exception("ffprobe and ffmpeg not found")))
    e = downloader.friendly_error(Exception("algo estranho"))
    assert e.detail == "algo estranho"


def test_overall_percent():
    op = downloader.overall_percent
    assert op(0, 0.5, [300, 100]) == 37.5
    assert op(1, 0.0, [300, 100]) == 75.0
    assert op(1, 1.0, [300, 100]) == 99.0  # 100 só quando o job termina
    assert op(0, 0.5, [0, 0]) == 25.0  # sem tamanho: pesos iguais
    assert op(0, 0.5, []) == 50.0
    assert op(2, 0.5, [10, 10]) <= 99.0  # parte extra inesperada não explode


def test_info_local_file(media_server):
    info = downloader.extract_info(f"{media_server}/clipe%20teste.mp4")
    assert info["kind"] == "video"


def test_download_end_to_end(media_server):
    dl_id, job_id = _new_download(f"{media_server}/clipe%20teste.mp4")
    job = _run_job(job_id)
    assert job.status == "done", job.error_detail
    assert job.progress == 100
    with Session(engine) as s:
        dl = s.get(Download, dl_id)
        assert dl and dl.status == "done"
        path = Path(dl.file_path)
        assert path.is_file() and path.stat().st_size == dl.filesize
        assert path.is_relative_to(get_settings().data_dir / "downloads")


def test_download_error_is_friendly():
    dl_id, job_id = _new_download("http://127.0.0.1:9/nao-existe.mp4")
    job = _run_job(job_id)
    assert job.status == "error"
    with Session(engine) as s:
        dl = s.get(Download, dl_id)
        assert dl and dl.status == "error" and dl.error and dl.error_detail


def test_cancel_during_download(media_server, monkeypatch):
    dl_id, job_id = _new_download(f"{media_server}/clipe%20teste.mp4")
    real = downloader.download

    def slow_download(url, fmt, out_dir, on_progress, is_canceled, *a, **k):
        # o hook de progresso checa is_canceled; aqui forçamos o cancelamento antes de começar
        return real(url, fmt, out_dir, on_progress, lambda: True, *a, **k)

    monkeypatch.setattr(downloader, "download", slow_download)
    job = _run_job(job_id)
    assert job.status == "canceled"
    with Session(engine) as s:
        assert s.get(Download, dl_id).status == "canceled"  # type: ignore[union-attr]


# --- fila ---------------------------------------------------------------------
def test_queue_claim_cancel_retry_recover():
    with Session(engine) as s:
        # esvazia a fila de jobs leves pendentes de outros testes
        for j in s.exec(select(Job).where(Job.status == "queued")).all():
            j.status = "done"
            s.add(j)
        s.commit()
        a = enqueue(s, "download", 1)
        b = enqueue(s, "download", 2, priority=5)
        g = enqueue(s, "render", 3)
        assert g.uses_gpu and not a.uses_gpu
        first = claim(s, gpu=False, exclude_ids=set())
        assert first and first.id == b.id  # prioridade maior primeiro
        assert claim(s, gpu=True, exclude_ids=set()).id == g.id  # type: ignore[union-attr]
        # recover: running → queued
        assert recover_interrupted(s) >= 2
        s.refresh(b)
        assert b.status == "queued"
        cancel_job(s, a)
        assert a.status == "canceled"
        retry_job(s, a)
        assert a.status == "queued" and a.progress == 0
        for j in (a, b, g):
            cancel_job(s, j)


def test_worker_tick_runs_and_cancels(monkeypatch):
    started = threading.Event()

    def fake(ctx: tasks.JobContext) -> None:
        started.set()
        for i in range(100):
            ctx.check_canceled()
            ctx.report(i, f"passo {i}")
            time.sleep(0.02)

    monkeypatch.setitem(tasks.HANDLERS, "fake", fake)
    monkeypatch.setattr(runner, "HANDLERS", tasks.HANDLERS)
    with Session(engine) as s:
        job = enqueue(s, "fake", 0)
    w = runner.Worker()
    w.tick()
    assert started.wait(2)
    with Session(engine) as s:
        cancel_job(s, s.get(Job, job.id))  # type: ignore[arg-type]
    w.tick()  # percebe o cancelamento
    w.active[job.id][1].result(timeout=5)  # type: ignore[index]
    with Session(engine) as s:
        assert s.get(Job, job.id).status == "canceled"  # type: ignore[union-attr]

    # e um job que termina normalmente
    monkeypatch.setitem(tasks.HANDLERS, "ok", lambda ctx: ctx.report(50, "meio", force=True))
    with Session(engine) as s:
        job2 = enqueue(s, "ok", 0)
    w.tick()
    w.active[job2.id][1].result(timeout=5)  # type: ignore[index]
    with Session(engine) as s:
        j = s.get(Job, job2.id)
        assert j and j.status == "done" and j.progress == 100


def test_worker_shutdown_requeues(monkeypatch):
    started = threading.Event()

    def fake(ctx: tasks.JobContext) -> None:
        started.set()
        while True:
            ctx.check_canceled()
            time.sleep(0.02)

    monkeypatch.setitem(tasks.HANDLERS, "longo", fake)
    with Session(engine) as s:
        job = enqueue(s, "longo", 0)
    w = runner.Worker()
    w.tick()
    assert started.wait(2)
    w.running = False
    ctx, fut, _ = w.active[job.id]  # type: ignore[index]
    ctx.interrupted = True
    ctx.cancel()
    fut.result(timeout=5)
    with Session(engine) as s:
        j = s.get(Job, job.id)
        assert j and j.status == "queued"
        cancel_job(s, j)


# --- SSE ----------------------------------------------------------------------
def test_broker_detects_changes():
    b = Broker()
    assert b._poll_once() == []  # primeira passada só posiciona o cursor
    time.sleep(0.01)
    with Session(engine) as s:
        job = enqueue(s, "noop", 0)
    events = b._poll_once()
    assert any(e == "job.update" and d["id"] == job.id for e, d in events)
    assert b._poll_once() == []  # não repete
    with Session(engine) as s:
        cancel_job(s, s.get(Job, job.id))  # type: ignore[arg-type]
    events = b._poll_once()
    assert [d["status"] for e, d in events if d["id"] == job.id and e == "job.update"] == ["canceled"]


# --- API ----------------------------------------------------------------------
def test_api_download_flow(media_server):
    with TestClient(app) as c:
        r = c.post("/api/downloads/info", json={"url": f"{media_server}/clipe%20teste.mp4"})
        assert r.status_code == 200 and r.json()["kind"] == "video"
        r = c.post("/api/downloads/batch", json={"items": [
            {"url": f"{media_server}/clipe%20teste.mp4", "format_choice": "720p"},
            {"url": f"{media_server}/clipe%20teste.mp4", "format_choice": "audio_mp3"},
        ]})
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        jobs = c.get("/api/jobs", params={"status": "queued"}).json()
        assert {j["ref_id"] for j in jobs if j["type"] == "download"} >= set(ids)
        # cancelar um na fila
        assert c.post(f"/api/downloads/{ids[0]}/cancel").json()["status"] == "canceled"
        assert c.post(f"/api/downloads/{ids[0]}/retry").json()["status"] == "queued"
        assert c.post(f"/api/downloads/{ids[0]}/cancel").json()["status"] == "canceled"
        assert c.delete(f"/api/downloads/{ids[0]}").json()["ok"]
        assert c.get(f"/api/downloads/{ids[0]}").status_code == 404
        c.post(f"/api/downloads/{ids[1]}/cancel")
        # open-folder bloqueia caminhos fora de data/
        assert c.post("/api/system/open-folder", json={"path": "/etc"}).status_code == 403


def test_api_info_error():
    with TestClient(app) as c:
        r = c.post("/api/downloads/info", json={"url": "http://127.0.0.1:9/x.mp4"})
        assert r.status_code == 422
        assert r.json()["detail"]["message"]


def test_broker_empty_table_cursor():
    b = Broker()
    b._cursor = {Job: EPOCH, Download: EPOCH}  # estado após a 1ª passada com tabelas vazias
    assert isinstance(b._poll_once(), list)
