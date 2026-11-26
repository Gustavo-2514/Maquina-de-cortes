"""Fase 2: projetos, probe/proxy, forma de onda, transcrição (Whisper mockado) e /media com Range."""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine, init_db
from app.main import app
from app.models import Download, Job, Project
from app.services import highlighter, probe, proxy, transcriber
from app.worker import runner, tasks

init_db()
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("src") / "vídeo de teste.mp4"  # acento + espaço de propósito
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=300", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


def _run_next(job_type: str, ref_id: int) -> Job:
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.type == job_type, Job.ref_id == ref_id, Job.status == "queued")).first()
        assert job, f"nenhum job {job_type} na fila para {ref_id}"
        job.status = "running"
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)
    runner._execute(ctx)
    with Session(engine) as s:
        return s.get(Job, job.id)  # type: ignore[return-value]


FAKE_SENTENCES = ["Olá mundo, tudo bem com vocês?", "Hoje eu vou contar uma história incrível.",
                  "Prestem atenção até o final."]


def _fake_transcript() -> dict:
    segs, t = [], 0.0
    for i, sent in enumerate(FAKE_SENTENCES):
        words = []
        for w in sent.split():
            words.append({"w": w, "s": round(t, 2), "e": round(t + 0.4, 2), "p": 0.9})
            t += 0.5
        t += 0.8
        segs.append({"id": i, "start": words[0]["s"], "end": words[-1]["e"], "text": sent, "words": words})
    return {"language": "pt", "language_probability": 1.0, "model": "fake", "device": "cpu", "segments": segs}


def _fake_transcribe(audio, out, duration, lang, us, on_progress, is_canceled):
    on_progress(50, "meio")
    result = _fake_transcript()
    out.write_text(json.dumps(result))
    return result


def _fake_llm(url, model, is_canceled, on_chunk=None):
    def call(messages, temperature):
        return json.dumps({"clips": [{"start": 0.0, "end": 6.0, "title": "Olá", "hook": "Olá mundo", "reason": "teste",
                                      "scores": {"gancho": 8, "emocao": 6, "clareza": 9, "completude": 7}}]})
    return call


# --- unidades ---------------------------------------------------------------------
def test_probe(sample_video):
    info = probe.probe(sample_video)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (1280, 720)
    assert abs(info.duration_s - 12) < 0.2 and info.fps == 30


def test_postprocess_words():
    words = [{"w": " Olá", "s": 0.0, "e": 0.4, "p": 1}, {"w": ",", "s": 0.4, "e": 0.45, "p": 1},
             {"w": " zero", "s": 1.0, "e": 1.0, "p": 1}, {"w": " mundo", "s": 1.1, "e": 1.5, "p": 1},
             {"w": "!", "s": 1.5, "e": 1.5, "p": 1}]
    out = transcriber.postprocess_words(words)
    assert [w["w"] for w in out] == ["Olá,", "mundo!"]
    assert out[0]["e"] == 0.45


def test_peaks(tmp_path):
    wav = tmp_path / "a.wav"
    sig = (np.sin(np.linspace(0, 200 * np.pi, 16000 * 2)) * 10000).astype("<i2")
    sig[16000:] //= 4  # 2º segundo mais baixo
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(sig.tobytes())
    n = proxy.compute_peaks(wav, tmp_path / "p.json")
    data = json.loads((tmp_path / "p.json").read_text())
    assert n == 200 and data["rate"] == 100
    assert max(data["peaks"][:100]) == 1.0 and max(data["peaks"][100:]) < 0.3


def test_resolve_config_cpu(monkeypatch):
    from app.config import UserSettings
    from app.services import hardware

    monkeypatch.setattr(hardware, "detect_hardware", lambda: hardware.Hardware())
    monkeypatch.setattr(hardware, "cuda_available", lambda: (False, ""))
    assert transcriber.resolve_config(UserSettings()) == ("small", "cpu", "int8")
    assert transcriber.resolve_config(UserSettings(whisper_device="cuda"))[1] == "cpu"  # sem CUDA cai para CPU


# --- pipeline completo --------------------------------------------------------------
def test_pipeline_local_path(sample_video, monkeypatch):
    monkeypatch.setattr(transcriber, "transcribe", _fake_transcribe)
    monkeypatch.setattr(highlighter, "ollama_chat", _fake_llm)
    with TestClient(app) as c:
        r = c.post("/api/projects", json={"local_path": str(sample_video),
                                          "analyze": {"language": "pt", "num_clips": 5, "min_s": 20, "max_s": 60}})
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["origin"] == "local_path" and p["status"] == "processing" and p["name"] == "vídeo de teste"

        job = _run_next("probe_proxy", p["id"])
        assert job.status == "done", job.error_detail
        pdir = get_settings().project_dir(p["id"])
        for f in ("proxy.mp4", "audio.wav", "waveform.json", "meta.json"):
            assert (pdir / f).exists(), f
        assert len(list((pdir / "thumbs").glob("*.jpg"))) >= 1
        pinfo = probe.probe(pdir / "proxy.mp4")
        assert pinfo.height == 540 and pinfo.has_audio

        job = _run_next("transcribe", p["id"])
        assert job.status == "done", job.error_detail
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "processing" and p["stage"] == "analyze" and p["word_count"] == 18

        # ~9 s de fala para cortes de 20–60 s → erro amigável no projeto
        job = _run_next("analyze", p["id"])
        assert job.status == "error"
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "error" and "fala" in p["error"]

        t = c.get(f"/api/projects/{p['id']}/transcript").json()
        assert t["segments"][0]["words"][1]["w"] == "mundo,"
        t["segments"][0]["words"][1]["w"] = "mundão,"
        t["segments"][0]["words"][1]["s"] = 99  # tempos não podem mudar
        r = c.put(f"/api/projects/{p['id']}/transcript", json=t)
        assert r.status_code == 200
        w = r.json()["segments"][0]["words"][1]
        assert w["w"] == "mundão," and w["s"] == 0.5

        wf = c.get(f"/api/projects/{p['id']}/waveform").json()
        assert wf["length"] == pytest.approx(1200, abs=5)
        assert c.get(f"/api/projects/{p['id']}/thumbs").json()["urls"]

        # Range no proxy
        url = f"/api/media/projects/{p['id']}/proxy.mp4"
        r = c.get(url, headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        assert r.headers["content-range"].startswith("bytes 0-99/")

        # reanalisar reutiliza o cache (não refaz o proxy) e agora cabe (cortes de 5–10 s)
        mtime = (pdir / "proxy.mp4").stat().st_mtime
        c.post(f"/api/projects/{p['id']}/analyze", json={"language": "pt", "min_s": 5, "max_s": 10})
        assert _run_next("probe_proxy", p["id"]).message == "Concluído"
        assert (pdir / "proxy.mp4").stat().st_mtime == mtime
        assert _run_next("transcribe", p["id"]).status == "done"
        job = _run_next("analyze", p["id"])
        assert job.status == "done", job.error_detail
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "ready" and p["stage"] == "done"
        clips = c.get(f"/api/projects/{p['id']}/clips").json()
        assert len(clips) == 1
        clip = clips[0]
        assert clip["status"] == "suggested" and clip["start_s"] == 0.0 and clip["score"] > 0
        assert clip["hook_text"] == "Olá mundão, tudo bem com vocês?"  # usa a correção do usuário
        assert 5 <= clip["end_s"] - clip["start_s"] <= 10.2

        # edição, corte manual, duplicar, descartar, apagar
        r = c.patch(f"/api/clips/{clip['id']}", json={"end_s": 7.3})
        assert r.json()["status"] == "edited" and r.json()["end_s"] == 7.3
        assert c.patch(f"/api/clips/{clip['id']}", json={"end_s": 0.2}).status_code == 422
        assert c.patch(f"/api/clips/{clip['id']}", json={"status": "discarded"}).json()["status"] == "discarded"
        m = c.post(f"/api/projects/{p['id']}/clips", json={"start_s": 3.3, "end_s": 9}).json()
        assert m["origin"] == "manual" and m["hook_text"] == "Hoje eu vou contar uma história incrível."
        assert c.post(f"/api/projects/{p['id']}/clips", json={"start_s": 0, "end_s": 999}).status_code == 422
        d = c.post(f"/api/clips/{m['id']}/duplicate").json()
        assert d["id"] != m["id"] and d["start_s"] == m["start_s"]
        assert c.delete(f"/api/clips/{d['id']}").json()["ok"]

        # reanálise substitui só sugestões/descartados da IA; manual fica
        c.post(f"/api/projects/{p['id']}/analyze", json={"language": "pt", "min_s": 5, "max_s": 10})
        for t in ("probe_proxy", "transcribe", "analyze"):
            assert _run_next(t, p["id"]).status == "done"
        clips = c.get(f"/api/projects/{p['id']}/clips").json()
        assert sorted(x["origin"] for x in clips) == ["ai", "manual"]

        # apagar remove a pasta derivada, mas não o arquivo-fonte local
        assert c.delete(f"/api/projects/{p['id']}").json()["ok"]
        assert not pdir.exists() and sample_video.exists()


def test_download_to_project_and_auto(sample_video, monkeypatch):
    monkeypatch.setattr(transcriber, "transcribe", _fake_transcribe)
    dest = get_settings().data_dir / "downloads" / "baixado [abc].mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_video, dest)
    with Session(engine) as s:
        dl = Download(url="http://x", title="Baixado", status="done", file_path=str(dest), format_choice="best")
        audio = Download(url="http://y", title="Áudio", status="done", file_path=str(dest), format_choice="audio_mp3")
        pending = Download(url="http://z", title="Pendente", status="downloading")
        s.add_all([dl, audio, pending])
        s.commit()
        ids = dl.id, audio.id, pending.id
    with TestClient(app) as c:
        r = c.post(f"/api/downloads/{ids[0]}/to-project")
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["name"] == "Baixado" and p["status"] == "new" and p["download_id"] == ids[0]
        assert c.get(f"/api/downloads/{ids[0]}").json()["project_id"] == p["id"]
        assert c.post(f"/api/downloads/{ids[0]}/to-project").status_code == 409  # já existe
        assert c.post(f"/api/downloads/{ids[1]}/to-project").status_code == 422  # só áudio
        assert c.post(f"/api/downloads/{ids[2]}/to-project").status_code == 409  # não terminou
        # arquivo usado por projeto não pode ser apagado pelo download
        assert c.delete(f"/api/downloads/{ids[0]}?delete_file=true").status_code == 409

        # analisar a partir da tela do projeto
        assert c.post(f"/api/projects/{p['id']}/analyze", json={"min_s": 60, "max_s": 30}).status_code == 422
        assert c.post(f"/api/projects/{p['id']}/analyze", json={}).json()["status"] == "processing"
        c.delete(f"/api/projects/{p['id']}")
        assert c.get(f"/api/downloads/{ids[0]}").json()["project_id"] is None
        assert dest.exists()  # o arquivo do download continua

    # send_to_project: a criação acontece ao fim do handler de download
    with Session(engine) as s:
        dl2 = Download(url="http://w", title="Auto", status="done", file_path=str(dest), send_to_project=True)
        s.add(dl2)
        s.commit()
        s.refresh(dl2)
        dl2_id = dl2.id
        monkeypatch.setattr(tasks.downloader, "download", lambda *a, **k: dest)
        job = Job(type="download", ref_id=dl2.id, status="running")  # type: ignore[arg-type]
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)
    runner._execute(ctx)
    with Session(engine) as s:
        dl2 = s.get(Download, dl2_id)
        assert dl2 and dl2.project_id
        proj = s.get(Project, dl2.project_id)
        assert proj and proj.status == "processing"
        assert s.exec(select(Job).where(Job.type == "probe_proxy", Job.ref_id == proj.id)).first()


def test_upload_and_errors(sample_video):
    with TestClient(app) as c:
        data = sample_video.read_bytes()
        r = c.post("/api/projects/upload", params={"filename": "meu vídeo.mp4", "name": "Upload"}, content=data)
        assert r.status_code == 200, r.text
        p = r.json()
        src = Path(p["source_path"])
        assert p["origin"] == "upload" and src.read_bytes() == data
        assert c.post("/api/projects/upload", params={"filename": "x.exe"}, content=b"abc").status_code == 422
        assert c.post("/api/projects", json={"local_path": "/nao/existe.mp4"}).status_code == 404
        assert c.post("/api/projects", json={}).status_code == 422
        c.delete(f"/api/projects/{p['id']}")
        assert not src.exists()


def test_media_blocks_traversal():
    with TestClient(app) as c:
        r = c.get("/api/media/../../etc/passwd")  # o cliente normaliza para /etc/passwd → SPA
        assert "root:" not in r.text
        assert c.get("/api/media/%2e%2e/%2e%2e/etc/passwd").status_code in (403, 404)
        assert c.get("/api/media/nada.mp4").status_code == 404
    from fastapi import HTTPException

    from app.api.media import resolve_media

    for bad in ("../../etc/passwd", "/etc/passwd", "projects/../../x"):
        with pytest.raises(HTTPException) as e:
            resolve_media(bad)
        assert e.value.status_code in (403, 404)


def test_probe_error_marks_project(tmp_path):
    bad = tmp_path / "ruim.mp4"
    bad.write_bytes(b"isso nao e video")
    with TestClient(app) as c:
        p = c.post("/api/projects", json={"local_path": str(bad), "analyze": {}}).json()
        job = _run_next("probe_proxy", p["id"])
        assert job.status == "error"
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "error" and p["error"]
        c.delete(f"/api/projects/{p['id']}")


def test_auto_render_is_a_pipeline_stage(sample_video, monkeypatch):
    """auto_render: análise → etapa "render" → projeto só fica pronto quando o último MP4 sai."""
    monkeypatch.setattr(transcriber, "transcribe", _fake_transcribe)
    monkeypatch.setattr(highlighter, "ollama_chat", _fake_llm)
    with TestClient(app) as c:
        p = c.post("/api/projects", json={"local_path": str(sample_video), "analyze": {
            "language": "pt", "min_s": 5, "max_s": 10, "reframe_mode": "center", "auto_render": True}}).json()
        for t in ("probe_proxy", "transcribe", "analyze"):
            assert _run_next(t, p["id"]).status == "done"
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "processing" and p["stage"] == "render"
        clip = c.get(f"/api/projects/{p['id']}/clips").json()[0]

        job = _run_next("render", clip["id"])
        assert job.status == "done", job.error_detail
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["status"] == "ready" and p["stage"] == "done" and p["progress"] == 100
        assert c.get(f"/api/clips/{clip['id']}").json()["status"] == "rendered"

        # render avulso depois não mexe no estado do projeto
        c.patch(f"/api/clips/{clip['id']}", json={"end_s": 7.0})
        c.post(f"/api/clips/{clip['id']}/render")
        assert _run_next("render", clip["id"]).status == "done"
        assert c.get(f"/api/projects/{p['id']}").json()["status"] == "ready"
        c.delete(f"/api/projects/{p['id']}")


def test_download_carries_analysis_options(sample_video, monkeypatch):
    """Tipo de conteúdo e auto_render escolhidos ao colar o link chegam ao projeto; idioma vem das Configurações."""
    dest = get_settings().data_dir / "downloads" / "opcoes [xyz].mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_video, dest)
    monkeypatch.setattr(tasks.downloader, "download", lambda *a, **k: dest)
    with TestClient(app) as c:
        r = c.post("/api/downloads/batch", json={"items": [{"url": "http://opcoes", "send_to_project": True,
                                                            "analyze": {"template": "gameplay", "reframe_mode": "gameplay",
                                                                        "auto_render": True}}]})
        assert r.status_code == 200, r.text
        dl_id = r.json()[0]["id"]
    assert _run_next("download", dl_id).status == "done"
    with Session(engine) as s:
        dl = s.get(Download, dl_id)
        proj = s.get(Project, dl.project_id)  # type: ignore[union-attr, arg-type]
        opts = json.loads(proj.settings_json)  # type: ignore[union-attr]
    assert opts["template"] == "gameplay" and opts["reframe_mode"] == "gameplay" and opts["auto_render"] is True
    assert opts["language"] == tasks.load_user_settings().default_language
