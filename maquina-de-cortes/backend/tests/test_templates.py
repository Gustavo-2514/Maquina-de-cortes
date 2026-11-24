"""Templates: quem fala (podcast), webcam + jogo (gameplay), prompts e aplicar template."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import get_settings
from app.db import engine, init_db
from app.main import app
from app.models import Clip, Project
from app.services import highlighter as hl
from app.services import reframer, renderer
from app.services.templates import TEMPLATES, get_template

init_db()
FPS = reframer.FACE_FPS


def lips(talking: bool, i: int) -> float:
    """Abertura dos lábios: falando oscila (0,05–0,35); calado fica parada (~0,08)."""
    return 0.2 + 0.15 * math.sin(i * 2.1) if talking else 0.08


def person(cx, i, talking, legible=True, size=0.25):
    return [cx, 0.4, size * 0.56, size, 0.95, 0.0, 0.4 if legible else 0.15, lips(talking, i) if legible else -1]


def faces_for(dur, fn):
    return {"version": reframer.FACES_VERSION, "fps": FPS, "frames": [fn(i) for i in range(int(dur * FPS))]}


SPEECH = [(0.0, 60.0)]


def test_speaker_follows_who_talks_with_hard_cuts():
    # esquerda fala 0–6 s, direita 6–14 s, esquerda 14–20 s (os dois sempre visíveis e de frente)
    def fn(i):
        t = i / FPS
        left = t < 6 or t >= 14
        return [person(0.25, i, left), person(0.72, i, not left)]

    tr = reframer.compute_track(faces_for(20, fn), [], 0, 20, 1920, 1080, 10, "speaker", speech=SPEECH)
    cx = np.array(tr.cx)
    assert len(tr.switches) == 2
    assert abs(tr.switches[0] - 6) <= 0.8 and abs(tr.switches[1] - 14) <= 0.8
    assert abs(cx[30] - 0.25) < 0.03 and abs(cx[100] - 0.72) < 0.03 and abs(cx[180] - 0.25) < 0.03
    i = int(tr.switches[0] * 10)
    assert abs(cx[i] - cx[i - 1]) > 0.3  # corte seco, sem deslizar


def test_speaker_exclusion_with_profile_face():
    # direita de perfil (lábios ilegíveis) fala 5–12 s; esquerda (legível) fala no resto
    def fn(i):
        t = i / FPS
        right_talks = 5 <= t < 12
        return [person(0.25, i, not right_talks), person(0.72, i, False, legible=False)]

    tr = reframer.compute_track(faces_for(16, fn), [], 0, 16, 1920, 1080, 10, "speaker", speech=SPEECH)
    cx = np.array(tr.cx)
    assert abs(cx[20] - 0.25) < 0.03  # esquerda fala
    assert abs(cx[85] - 0.72) < 0.03  # esquerda calada + há voz → fala quem está de perfil
    assert abs(cx[150] - 0.25) < 0.03


def test_speaker_hysteresis_ignores_short_blips():
    # direita "fala" só 0,4 s no meio: não pode trocar
    def fn(i):
        t = i / FPS
        blip = 4.0 <= t < 4.4
        return [person(0.25, i, not blip), person(0.72, i, blip)]

    tr = reframer.compute_track(faces_for(10, fn), [], 0, 10, 1920, 1080, 10, "speaker", speech=SPEECH)
    assert tr.switches == []


def test_speaker_no_switch_without_speech():
    def fn(i):
        return [person(0.25, i, i / FPS < 5), person(0.72, i, i / FPS >= 5)]

    tr = reframer.compute_track(faces_for(10, fn), [], 0, 10, 1920, 1080, 10, "speaker", speech=[(0, 4.0)])
    assert tr.switches == []  # depois de 4 s não há fala: ninguém troca por movimento de boca


def test_detect_webcam_and_gameplay_boxes():
    # facecam fixa no canto inferior direito; rostos do jogo passam em lugares aleatórios
    rnd = np.random.default_rng(0)

    def fn(i):
        out = [[0.86 + rnd.normal(0, 0.003), 0.78 + rnd.normal(0, 0.003), 0.05, 0.09, 0.9, 0, 0.4, -1]]
        if i % 3 == 0:
            out.append([float(rnd.uniform(0.1, 0.7)), float(rnd.uniform(0.2, 0.6)), 0.04, 0.07, 0.8, 0, 0.4, -1])
        return out

    faces = faces_for(60, fn)
    cam_face = reframer.detect_webcam(faces)
    assert cam_face and abs(cam_face[0] - 0.86) < 0.01 and abs(cam_face[1] - 0.78) < 0.01
    g = reframer.gameplay_boxes(1920, 1080, cam_face)
    x, y, w, h = g["cam"]
    assert x <= 0.86 <= x + w and y <= 0.78 <= y + h  # a webcam contém o rosto
    assert 0 <= x and x + w <= 1 and 0 <= y and y + h <= 1
    top_h = round(g["top_ratio"] * 1920)
    assert abs((w * 1920) / (h * 1080) - 1080 / top_h) < 0.02  # proporção do painel de cima
    gx, gy, gw, gh = g["game"]
    assert abs(gx + gw / 2 - 0.5) < 0.01  # jogo centralizado
    assert abs((gw * 1920) / (gh * 1080) - 1080 / (1920 - top_h)) < 0.02
    # ajustes do editor: mais webcam, jogo deslocado
    g2 = reframer.gameplay_boxes(1920, 1080, cam_face, {"top_ratio": 0.5, "cam_center": [0.2, 0.3], "cam_w": 0.2,
                                                        "game_cx": 0.3})
    assert g2["top_ratio"] == 0.5 and abs(g2["cam"][0] + g2["cam"][2] / 2 - 0.2) < 0.01
    assert g2["game"][0] + g2["game"][2] / 2 < 0.5
    # sem webcam estável → None (render cai para o jogo inteiro com fundo borrado)
    assert reframer.detect_webcam(faces_for(20, lambda i: [[float(rnd.uniform(0, 1)), 0.5, 0.05, 0.09, 0.9]])) is None
    assert reframer.gameplay_boxes(1920, 1080, None)["cam"] is None


def test_gameplay_filter_graph():
    spec = renderer.RenderSpec(source=__import__("pathlib").Path("x.mp4"), start_s=0, end_s=10, src_w=1920, src_h=1080,
                               src_fps=60, mode="gameplay",
                               gameplay=reframer.gameplay_boxes(1920, 1080, [0.86, 0.78, 0.05, 0.09]))
    fc = renderer.video_filter(spec)
    assert "vstack=inputs=2" in fc and fc.count("crop=") == 2 and "scale=1080:614" in fc and "scale=1080:1306" in fc  # 32/68
    spec.gameplay = reframer.gameplay_boxes(1920, 1080, None)
    assert "gblur" in renderer.video_filter(spec)  # sem webcam: jogo inteiro sobre fundo borrado


def test_template_prompt_and_loudness():
    t = get_template("gameplay")
    assert t.reframe_mode == "gameplay" and t.loudness_hints and t.caption_position_y == 0.82 and t.caption_font_size == 70
    assert get_template("nao-existe").key == "geral"
    rms = np.ones(200)
    rms[50:60] = 5  # grito entre 5 e 6 s
    tr = {"segments": [{"start": 0, "end": 2, "words": [{"w": "oi", "s": 0, "e": 1, "p": 1}]},
                       {"start": 5, "end": 6, "words": [{"w": "NÃO!", "s": 5, "e": 5.9, "p": 1}]}]}
    lines = hl.transcript_lines(tr, 0, 20, rms, float(rms.mean()))
    assert "[VOLUME ALTO]" in lines.splitlines()[1] and "[VOLUME ALTO]" not in lines.splitlines()[0]
    assert "[VOLUME ALTO]" not in hl.transcript_lines(tr, 0, 20)  # sem áudio, sem marca

    seen = {}

    def llm(messages, temperature):
        seen["system"] = messages[0]["content"]
        return json.dumps({"clips": []})

    words = [{"w": f"p{i}.", "s": i * 1.0, "e": i + 0.8, "p": 1} for i in range(60)]
    hl.find_highlights({"segments": [{"start": 0, "end": 60, "words": words}]}, 60, 3, 20, 40, "foco no fim", llm,
                       template=t)
    assert "GAMEPLAY" in seen["system"] and "foco no fim" in seen["system"]


def test_reactions_heuristic_prefers_loud_peaks():
    words = hl.Words.from_transcript({"segments": [{"start": 0, "end": 60, "words": [
        {"w": f"p{i}.", "s": i * 1.0, "e": i + 0.8, "p": 1} for i in range(60)]}]})
    rms = np.ones(600)
    rms[300:320] = 6  # grito em 30–32 s
    quiet = hl.heuristic_score(words, 0, 20, rms, float(rms.mean()), "reactions")
    loud = hl.heuristic_score(words, 25, 45, rms, float(rms.mean()), "reactions")
    assert loud["heuristica"] > quiet["heuristica"] + 30


def test_templates_api_and_apply():
    with TestClient(app) as c:
        ts = c.get("/api/templates").json()
        assert [t["key"] for t in ts] == list(TEMPLATES)
        with Session(engine) as s:
            p = Project(name="T", source_path="/x.mp4", origin="local_path", duration_s=100, width=1920, height=1080,
                        fps=30, status="ready", stage="done")
            s.add(p)
            s.commit()
            s.refresh(p)
            pid = p.id
            a = Clip(project_id=pid, start_s=0, end_s=20, reframe_mode="auto", status="rendered", output_path="/o.mp4",
                     caption_overrides_json=json.dumps({"words": {"1.000": "oi"}}))
            b = Clip(project_id=pid, start_s=30, end_s=50, reframe_mode="auto", status="discarded")
            s.add_all([a, b])
            s.commit()
            aid, bid = a.id, b.id
        r = c.post(f"/api/projects/{pid}/apply-template", json={"template": "gameplay"}).json()
        assert r["clips"] == 1 and r["renders"] == 0
        ca = c.get(f"/api/clips/{aid}").json()
        assert ca["reframe_mode"] == "gameplay" and ca["status"] == "edited"  # MP4 ficou desatualizado
        ov = json.loads(ca["caption_overrides_json"])
        assert ov["words"] == {"1.000": "oi"} and ov["style"]["position_y"] == 0.82 and ov["style"]["font_size"] == 70  # correções preservadas
        assert c.get(f"/api/clips/{bid}").json()["reframe_mode"] == "auto"  # descartado não muda
        assert json.loads(c.get(f"/api/projects/{pid}").json()["settings_json"])["template"] == "gameplay"
        c.post(f"/api/projects/{pid}/apply-template", json={"template": "geral"})
        assert "position_y" not in json.loads(c.get(f"/api/clips/{aid}").json()["caption_overrides_json"])["style"]
        assert c.post(f"/api/projects/{pid}/apply-template", json={"template": "xx"}).status_code == 422
        # corte manual herda o template do projeto
        c.post(f"/api/projects/{pid}/apply-template", json={"template": "debate"})
        m = c.post(f"/api/projects/{pid}/clips", json={"start_s": 60, "end_s": 80}).json()
        assert m["reframe_mode"] == "split" and json.loads(m["caption_overrides_json"])["style"]["position_y"] == 0.5
        c.delete(f"/api/projects/{pid}")
