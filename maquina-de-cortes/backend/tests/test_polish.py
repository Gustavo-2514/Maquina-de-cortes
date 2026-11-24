"""Fase 7: erros amigáveis, estimativa, armazenamento/limpeza e "preparar de novo"."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import UserSettings, get_settings
from app.db import engine, init_db
from app.errors import friendly
from app.estimate import estimate
from app.main import app
from app.models import Job, Project
from app.services.highlighter import HighlightError
from app.worker import runner, tasks

init_db()


def test_friendly_errors():
    assert "sem memória" in friendly(RuntimeError("CUDA failed with error out of memory"))[0]
    assert "disco está cheio" in friendly(OSError(errno.ENOSPC, "No space left on device"))[0]
    assert "não encontrado" in friendly(FileNotFoundError(2, "x", "/a/b.mp4"))[0]
    msg, detail = friendly(HighlightError("O LLM não devolveu um JSON válido.", "raw"))
    assert msg == "O LLM não devolveu um JSON válido." and detail == "raw"
    assert friendly(RuntimeError("Arquivo-fonte não encontrado: x"))[0] == "Arquivo-fonte não encontrado: x"
    assert "Erro inesperado (KeyError)" in friendly(KeyError("x"))[0]


def test_estimate_uses_cache(tmp_path, monkeypatch):
    from app.services import hardware

    monkeypatch.setattr(hardware, "detect_hardware", lambda: hardware.Hardware(cuda=True, vram_mb=8192, nvenc=True))
    monkeypatch.setattr(hardware, "cuda_available", lambda: (True, ""))
    est = estimate(tmp_path, 3600, "pt", UserSettings())
    stages = {s["key"]: s for s in est["stages"]}
    assert stages["transcribe"]["seconds"] == round(12 + 3600 / 6.5)
    assert est["gpu"] and est["total_seconds"] == sum(s["seconds"] for s in est["stages"])
    for f in ("proxy.mp4", "audio.wav", "waveform.json"):
        (tmp_path / f).write_bytes(b"x")
    (tmp_path / "transcript.json").write_text(json.dumps({"requested_language": "pt"}))
    est2 = estimate(tmp_path, 3600, "pt", UserSettings())
    s2 = {s["key"]: s for s in est2["stages"]}
    assert s2["prep"]["cached"] and s2["prep"]["seconds"] == 0 and s2["transcribe"]["seconds"] == 0
    assert estimate(tmp_path, 3600, "en", UserSettings())["stages"][1]["seconds"] > 0  # outro idioma: refaz


def _old(path: Path, days: int) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_storage_cleanup_and_prepare(tmp_path):
    data = get_settings().data_dir
    src = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    with TestClient(app) as c:
        p = c.post("/api/projects", json={"local_path": str(src), "analyze": {}}).json()
        pid = p["id"]
        with Session(engine) as s:  # roda só a preparação
            job = s.exec(select(Job).where(Job.type == "probe_proxy", Job.ref_id == pid)).first()
            job.status = "running"  # type: ignore[union-attr]
            s.add(job)
            s.commit()
            s.refresh(job)
            ctx = tasks.JobContext(job)  # type: ignore[arg-type]
        runner._execute(ctx)
        with Session(engine) as s:
            for j in s.exec(select(Job).where(Job.ref_id == pid, Job.status == "queued")).all():
                s.delete(j)  # não roda transcrição de verdade neste teste
            proj = s.get(Project, pid)
            proj.status, proj.stage = "ready", "done"  # type: ignore[union-attr]
            proj.updated_at = proj.updated_at.replace(year=2020)  # type: ignore[union-attr]
            s.add(proj)
            s.commit()
        pdir = get_settings().project_dir(pid)
        assert (pdir / "proxy.mp4").exists() and (pdir / "audio.wav").exists()

        # lixo: .part em downloads, pasta órfã de projeto
        (data / "downloads" / "x.mp4.part").write_bytes(b"0" * 1000)
        orphan = data / "projects" / "999999"
        orphan.mkdir(parents=True, exist_ok=True)
        (orphan / "proxy.mp4").write_bytes(b"0" * 2000)

        rep = c.get("/api/system/storage", params={"proxy_days": 30}).json()
        assert rep["cleanable"]["temp"]["count"] >= 2 and rep["cleanable"]["temp"]["bytes"] >= 3000
        assert pid in rep["cleanable"]["audio"]["projects"] and pid in rep["cleanable"]["proxies"]["projects"]
        assert rep["free_bytes"] > 0 and set(rep["folders"]) == {"downloads", "projects", "exports", "logs"}

        r = c.post("/api/system/cleanup", json={"temp": True, "audio": True, "proxies": True, "proxy_days": 30}).json()
        assert r["removed"] >= 4 and r["freed_bytes"] > 3000
        assert not orphan.exists() and not (data / "downloads" / "x.mp4.part").exists()
        files = c.get(f"/api/projects/{pid}/files").json()
        assert files == {**files, "proxy": False, "audio": False, "waveform": True, "thumbs": True}

        # "preparar de novo": regera só proxy + áudio e NÃO enfileira transcrição/análise
        thumb_mtime = next((pdir / "thumbs").glob("*.jpg")).stat().st_mtime
        assert c.post(f"/api/projects/{pid}/prepare").json()["status"] == "processing"
        assert c.post(f"/api/projects/{pid}/prepare").status_code == 409  # já em andamento
        with Session(engine) as s:
            job = s.exec(select(Job).where(Job.type == "probe_proxy", Job.ref_id == pid, Job.status == "queued")).first()
            job.status = "running"  # type: ignore[union-attr]
            s.add(job)
            s.commit()
            s.refresh(job)
            ctx = tasks.JobContext(job)  # type: ignore[arg-type]
        runner._execute(ctx)
        files = c.get(f"/api/projects/{pid}/files").json()
        assert files["proxy"] and files["audio"]
        assert next((pdir / "thumbs").glob("*.jpg")).stat().st_mtime == thumb_mtime  # miniaturas não refeitas
        proj = c.get(f"/api/projects/{pid}").json()
        assert proj["status"] == "ready" and proj["prepare_only"] is False
        with Session(engine) as s:
            queued = {j.type for j in s.exec(select(Job).where(Job.ref_id == pid, Job.status == "queued")).all()}
        assert "transcribe" not in queued

        est = c.get(f"/api/projects/{pid}/estimate", params={"language": "pt"}).json()
        assert est["stages"][0]["cached"] is True
        c.delete(f"/api/projects/{pid}")


def test_cleanup_refused_while_running():
    with Session(engine) as s:
        j = Job(type="render", ref_id=0, status="running")
        s.add(j)
        s.commit()
        s.refresh(j)
        jid = j.id
    with TestClient(app) as c:
        assert c.post("/api/system/cleanup", json={"temp": True}).status_code == 409
    with Session(engine) as s:
        s.delete(s.get(Job, jid))
        s.commit()
