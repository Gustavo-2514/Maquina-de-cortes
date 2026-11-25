"""Pacote para postar (roadmap #9): textos por plataforma, capa automática e exportação em .zip."""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import get_settings
from app.db import engine, init_db
from app.main import app
from app.models import Clip, Job, Project
from app.services import highlighter, postpack
from app.worker import runner, tasks

init_db()

LLM_OK = {
    "tiktok": {"legenda": "Ele não esperava essa resposta 😳 #fyp", "hashtags": ["#Saúde Mental", "fyp", "FYP", "podcast"]},
    "reels": {"legenda": "O que você faria? Comenta aí.", "hashtags": ["podcast", "cortes", "#reflexão", "", "1"]},
    "shorts": {"titulo": "\"A resposta que ninguém esperava\"", "descricao": "Um trecho sobre escolhas.",
               "hashtags": ["shorts", "podcast", "#Brasil"]},
}


# --- normalização ------------------------------------------------------------------
def test_clean_hashtags():
    assert postpack.clean_hashtag("#Saúde Mental!") == "SaudeMental"
    assert postpack.clean_hashtag("café") == "cafe"
    # sem repetidas (ignora maiúsculas), sem vazias/números, respeita limite e exclusões
    assert postpack.clean_hashtags(["fyp", "FYP", "", "123", "#a", "Podcast", "x1", "y2"], 3) == ["fyp", "Podcast", "x1"]
    assert postpack.clean_hashtags("#shorts #humor, #Shorts", 3, exclude={"shorts"}) == ["humor"]


def test_normalize_post():
    p = postpack.normalize_post(LLM_OK)
    assert p["tiktok"]["caption"] == "Ele não esperava essa resposta 😳"  # hashtag removida do texto
    assert p["tiktok"]["hashtags"] == ["SaudeMental", "fyp", "podcast"]
    assert p["reels"]["hashtags"] == ["podcast", "cortes", "reflexao"]
    assert p["shorts"]["title"] == "A resposta que ninguém esperava"
    assert p["shorts"]["hashtags"] == ["podcast", "Brasil"]  # #shorts entra sozinha no texto final
    assert postpack.platform_text(p, "shorts").endswith("#podcast #Brasil #Shorts")
    assert postpack.platform_text(p, "tiktok") == "Ele não esperava essa resposta 😳\n\n#SaudeMental #fyp #podcast"
    # formato salvo (edição manual) também é aceito
    assert postpack.normalize_post(p) == p
    with pytest.raises(ValueError):
        postpack.normalize_post({"tiktok": {"legenda": ""}})


def test_long_texts_are_trimmed():
    long = "Frase curta. " * 60
    p = postpack.normalize_post({"tiktok": {"legenda": long, "hashtags": []}, "reels": {}, "shorts": {"titulo": "x" * 300}})
    assert len(p["tiktok"]["caption"]) <= postpack.CAPTION_MAX["tiktok"] and p["tiktok"]["caption"].endswith(".")
    assert len(p["shorts"]["title"]) <= postpack.SHORTS_TITLE_MAX


def test_messages_language_and_truncation():
    msgs = postpack.build_post_messages("T", "Gancho", "palavra " * 2000, "en", 42, "Podcast X")
    assert "inglês" in msgs[0]["content"]
    assert "Podcast X" in msgs[1]["content"] and len(msgs[1]["content"]) < postpack.TRANSCRIPT_MAX_CHARS + 300


# --- capa ------------------------------------------------------------------------------
def test_face_quality_prefers_big_frontal_closed_mouth():
    big = [0.5, 0.4, 0.2, 0.3, 0.9, 0, 0.4, 0.02]
    profile = [0.5, 0.4, 0.2, 0.3, 0.9, 0, 0.15, 0.02]
    yelling = [0.5, 0.4, 0.2, 0.3, 0.9, 0, 0.4, 0.12]
    small = [0.5, 0.4, 0.05, 0.08, 0.9, 0, 0.4, 0.02]
    q = postpack.face_quality
    assert q([big]) > q([yelling]) > 0 and q([big]) > q([profile]) and q([big]) > q([small])
    assert q([big], window=(0.0, 0.3)) == 0  # rosto fora do crop não conta
    assert q([]) == 0


def test_cover_candidates_and_pick():
    frames = [[] for _ in range(100)]  # 20 s a 5 fps
    frames[30] = [[0.5, 0.4, 0.1, 0.15, 0.9, 0, 0.4, 0.02]]  # 6,0 s
    frames[31] = [[0.5, 0.4, 0.2, 0.3, 0.9, 0, 0.4, 0.02]]  # 6,2 s: rosto maior
    frames[45] = [[0.5, 0.4, 0.3, 0.4, 0.9, 0, 0.4, 0.02]]  # 9,0 s mas colado numa troca de cena
    cands = postpack.cover_candidates({"fps": 5, "frames": frames}, [9.1], 2.0, 18.0, n=4)
    assert len(cands) == 4 and all(2.0 < c.t < 18.0 for c in cands)
    assert any(c.t == 6.2 for c in cands) and not any(c.t == 9.0 for c in cands)
    for c in cands:
        c.sharp = 100.0
    assert postpack.pick_cover(cands).t == 6.2
    # sem rostos: decide só pela nitidez
    flat = postpack.cover_candidates({}, [], 0, 10, n=3)
    for c, s in zip(flat, (10, 50, 20)):
        c.sharp = s
    assert postpack.pick_cover(flat) is flat[1]


def test_sharpness_blur_vs_detail():
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, (400, 300, 3), dtype=np.uint8)
    flat = np.full((400, 300, 3), 128, np.uint8)
    assert postpack.sharpness(noisy) > postpack.sharpness(flat)


# --- exportação ------------------------------------------------------------------------
def test_csv_and_txt(tmp_path):
    post = postpack.normalize_post(LLM_OK)
    items = [postpack.ExportItem(mp4=tmp_path / "a.mp4", name="87_a.mp4", score=87.4, duration_s=61.2, title="A",
                                 post=post, cover=tmp_path / "c.jpg"),
             postpack.ExportItem(mp4=tmp_path / "b.mp4", name="64_b.mp4", score=64, duration_s=30, title="B", post={})]
    text = postpack.csv_text(items)
    assert text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(text[1:])))
    assert rows[0]["arquivo"] == "87_a.mp4" and rows[0]["capa"] == "capas/87_a.jpg" and rows[0]["nota"] == "87"
    assert rows[0]["shorts_hashtags"] == "#podcast #Brasil #Shorts"
    assert rows[1]["shorts_titulo"] == "B" and rows[1]["capa"] == ""
    txt = postpack.txt_text(items, "Projeto", skipped=2)
    assert "2 sem MP4" in txt and "--- TikTok ---" in txt and "textos ainda não gerados" in txt


# --- de ponta a ponta: render → pacote (IA falsa) → .zip --------------------------------
def _run(job_id: int) -> Job:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        job.status = "running"  # type: ignore[union-attr]
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)  # type: ignore[arg-type]
    runner._execute(ctx)
    with Session(engine) as s:
        return s.get(Job, job_id)  # type: ignore[return-value]


def W(text, s, e):
    return {"w": text, "s": s, "e": e, "p": 0.9}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_post_pack_end_to_end(tmp_path, monkeypatch):
    calls = []

    def fake_chat(url, model, is_canceled, on_chunk=None, schema=None):
        assert schema is postpack.POST_SCHEMA

        def call(messages, temperature):
            calls.append(messages)
            return "isso não é json" if len(calls) == 1 else json.dumps(LLM_OK)  # 1ª resposta inválida → repete

        return call

    monkeypatch.setattr(highlighter, "ollama_chat", fake_chat)
    src = tmp_path / "fonte.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    with Session(engine) as s:
        p = Project(name="Pacote teste", source_path=str(src), origin="local_path", duration_s=8, width=1280,
                    height=720, fps=30, status="ready", stage="done", faces_ready=True)
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
        pdir = get_settings().project_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "transcript.json").write_text(json.dumps({"segments": [{"id": 0, "start": 1, "end": 4, "text": "",
            "words": [W("Olá", 1.0, 1.5), W("pessoal,", 1.6, 2.2), W("tudo", 2.4, 2.8), W("certo?", 2.9, 3.6)]}]}))
        # um rosto à direita entre 2 s e 3 s: o modo "auto" segue (caminho do crop por quadro)
        frames = [[] for _ in range(40)]
        for i in range(10, 15):
            frames[i] = [[0.7, 0.4, 0.1, 0.2, 0.9, 0, 0.4, 0.02]]
        (pdir / "faces.json").write_text(json.dumps({"version": 5, "fps": 5, "frames": frames}))
        (pdir / "scenes.json").write_text(json.dumps({"cuts": []}))
        shutil.copy(src, pdir / "proxy.mp4")
        clips = [Clip(project_id=pid, title="Corte A", start_s=1.0, end_s=5.0, score=87, reframe_mode="auto"),
                 Clip(project_id=pid, title="Corte B", start_s=2.0, end_s=6.0, score=64, reframe_mode="blur_fit"),
                 Clip(project_id=pid, title="Descartado", start_s=0, end_s=3, status="discarded")]
        s.add_all(clips)
        s.commit()
        a, b, d = (c.id for c in clips)

    with TestClient(app) as c:
        assert c.get(f"/api/projects/{pid}/export.zip").status_code == 409  # nada renderizado ainda
        assert c.get(f"/api/clips/{a}/cover").status_code == 404
        assert c.post(f"/api/clips/{d}/post-pack", json={}).status_code == 409
        jobs = c.post(f"/api/projects/{pid}/post-pack", json={}).json()
        assert sorted(j["ref_id"] for j in jobs) == [a, b] and all(j["type"] == "post_pack" and j["uses_gpu"] for j in jobs)
        assert {j["id"] for j in c.post(f"/api/projects/{pid}/post-pack", json={}).json()} == {j["id"] for j in jobs}
        q = c.get("/api/jobs", params={"status": "queued"}).json()
        assert any(j["id"] == jobs[0]["id"] and j["target"].startswith("Corte") for j in q)

    for j in jobs:
        done = _run(j["id"])
        assert done.status == "done", done.error_detail

    with TestClient(app) as c:
        ca = c.get(f"/api/clips/{a}").json()
        post = json.loads(ca["post_json"])
        assert post["tiktok"]["hashtags"] == ["SaudeMental", "fyp", "podcast"] and post["model"]
        assert 0 <= post["cover_t"] <= 4 and post["cover_title"] is True
        assert ca["status"] == "suggested"  # gerar o pacote não invalida o MP4
        assert "Olá pessoal, tudo certo?" in calls[0][1]["content"]
        for cid in (a, b):
            for titled in (False, True):
                r = c.get(f"/api/clips/{cid}/cover", params={"titled": titled})
                assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
        import cv2

        img = cv2.imread(str(pdir / "clips" / str(a) / "cover.jpg"))
        assert img.shape[:2] == (1920, 1080)

        # tudo já existe → nada a fazer; só a capa de novo para um corte
        assert c.post(f"/api/projects/{pid}/post-pack", json={}).status_code == 409
        j = c.post(f"/api/clips/{b}/post-pack", json={"texts": False, "cover": True}).json()
        assert json.loads(c.get(f"/api/jobs").json()[0]["params_json"]) == {"texts": False, "cover": True}
        n_calls = len(calls)
        assert _run(j["id"]).status == "done" and len(calls) == n_calls

        # edição manual: normaliza e mantém os dados da capa
        r = c.put(f"/api/clips/{a}/post", json={"tiktok": {"caption": "Novo texto", "hashtags": ["#um", "dois"]},
                                                 "reels": post["reels"], "shorts": post["shorts"]})
        assert r.status_code == 200
        edited = json.loads(r.json()["post_json"])
        assert edited["tiktok"] == {"caption": "Novo texto", "hashtags": ["um", "dois"]} and edited["cover_t"] == post["cover_t"]
        assert r.json()["status"] == "suggested"
        assert c.put(f"/api/clips/{a}/post", json={}).status_code == 422

        # render de um corte só → zip leva esse MP4 + capas + textos e avisa do que ficou de fora
        assert _run(c.post(f"/api/clips/{a}/render").json()["id"]).status == "done"
        r = c.get(f"/api/projects/{pid}/export.zip")
        assert r.status_code == 200 and "pacote-teste-cortes.zip" in r.headers["content-disposition"]
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(z.namelist())
        assert names == {"87_corte-a.mp4", "capas/87_corte-a.jpg", "capas/87_corte-a-com-titulo.jpg", "textos.csv", "textos.txt"}
        txt = z.read("textos.txt").decode()
        assert "Novo texto" in txt and "1 sem MP4" in txt
        assert not list((get_settings().data_dir / "tmp").glob(f"export-{pid}-*"))  # zip temporário apagado
        c.delete(f"/api/projects/{pid}")
