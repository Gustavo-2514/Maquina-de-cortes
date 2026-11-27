"""Fase 5: trilha de crop (dados sintéticos) e render com crop variável."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from sqlmodel import Session

from app.config import get_settings
from app.db import engine, init_db
from app.models import Clip, Job, Project
from app.services import probe, reframer
from app.worker import runner, tasks

init_db()
SRC_W, SRC_H = 1920, 1080
CWN = reframer.crop_width(SRC_W, SRC_H) / SRC_W  # ~0,316
HALF = CWN / 2


def faces_for(duration: float, fn) -> dict:
    """faces.json sintético: fn(t) → lista de rostos [cx, cy, w, h, score]."""
    return {"version": reframer.FACES_VERSION, "fps": reframer.FACE_FPS,
            "frames": [fn(i / reframer.FACE_FPS) for i in range(int(duration * reframer.FACE_FPS))]}


def face(cx, cy=0.4, size=0.15, act=0.0):
    return [cx, cy, size * 9 / 16, size, 0.95, act]


# --- suavização -----------------------------------------------------------------
def test_smooth_deadzone_and_hold():
    rnd = random.Random(1)
    jitter = [0.4 + rnd.uniform(-0.01, 0.01) for _ in range(50)]
    out = reframer.smooth(jitter, deadzone=0.025)
    assert max(out) - min(out) < 0.005  # tremidinha do rosto não move o crop
    out = reframer.smooth([0.3] * 10 + [0.7] * 30, deadzone=0.025)
    assert out[0] == pytest.approx(0.3)  # começa no alvo, sem rampa
    assert out[-1] == pytest.approx(0.7, abs=0.01)  # converge para o novo alvo
    assert all(b >= a - 1e-9 for a, b in zip(out, out[1:]))  # sem oscilar
    out = reframer.smooth([0.6, None, None, 0.6], deadzone=0.02)
    assert out == pytest.approx([0.6] * 4)  # sem rosto: mantém
    assert reframer.smooth([None, None], 0.02) == [0.5, 0.5]


# --- trilha ---------------------------------------------------------------------
def test_track_follows_and_cuts_hard():
    rnd = random.Random(2)
    faces = faces_for(12, lambda t: [face(0.3 + rnd.uniform(-0.01, 0.01))] if t < 6 else [face(0.75 + rnd.uniform(-0.01, 0.01))])
    tr = reframer.compute_track(faces, [6.0], 1.0, 11.0, SRC_W, SRC_H, 30, "auto")
    assert tr.n == 300 and tr.cuts == [5.0]
    cx = np.array(tr.cx)
    before, after = cx[:150], cx[150:]
    assert before.std() < 0.003 and after.std() < 0.003  # não treme
    assert abs(before.mean() - 0.3) < 0.02 and abs(after.mean() - 0.75) < 0.02
    assert abs(cx[150] - 0.75) < 0.02  # salto seco no 1º frame da cena nova (sem rampa)
    assert abs(cx[149] - 0.3) < 0.02


def test_track_limits_and_no_faces():
    faces = faces_for(6, lambda t: [face(0.02)] if t < 3 else [])
    tr = reframer.compute_track(faces, [3.0], 0, 6, SRC_W, SRC_H, 25, "auto")
    cx = np.array(tr.cx)
    assert cx.min() >= HALF - 1e-9  # crop nunca sai do quadro
    assert abs(cx[:75].mean() - HALF) < 1e-6
    assert abs(cx[75:].mean() - 0.5) < 1e-6  # cena sem rosto → centro


def test_track_prefers_dominant_face():
    # rosto grande à direita sempre; rosto pequeno à esquerda aparece às vezes
    faces = faces_for(8, lambda t: [face(0.7, size=0.25)] + ([face(0.2, size=0.08)] if int(t) % 2 else []))
    tr = reframer.compute_track(faces, [], 0, 8, SRC_W, SRC_H, 30, "auto")
    assert abs(np.mean(tr.cx) - 0.7) < 0.02


def test_track_split_when_two_stable_faces():
    two = faces_for(10, lambda t: [face(0.25, 0.45), face(0.72, 0.4)])
    tr = reframer.compute_track(two, [], 0, 10, SRC_W, SRC_H, 30, "split")
    assert set(tr.layout) == {1}
    ax, ay, bx, by = tr.split[100]  # type: ignore[misc]
    assert ax == pytest.approx(0.25, abs=0.01) and bx == pytest.approx(0.72, abs=0.01)  # esquerda em cima
    # só 1 rosto no quadro → nunca divide
    one = faces_for(10, lambda t: [face(0.3)])
    tr = reframer.compute_track(one, [], 0, 10, SRC_W, SRC_H, 30, "split")
    assert set(tr.layout) == {0}


def test_split_per_moment_single_person_fills_screen():
    # 2 pessoas até 3 s, depois só a da direita: divide, depois ela em tela cheia e centralizada
    faces = faces_for(10, lambda t: ([face(0.25)] if t < 3 else []) + [face(0.7)])
    tr = reframer.compute_track(faces, [], 0, 10, SRC_W, SRC_H, 30, "split")
    assert set(tr.layout[:80]) == {1} and set(tr.layout[100:]) == {0}
    assert tr.cx[200] == pytest.approx(0.7, abs=0.02)
    # uma falha de detecção de 0,4 s no meio do debate não desfaz a divisão
    blip = faces_for(10, lambda t: [face(0.25), face(0.72)] if not 4 <= t < 4.4 else [face(0.72)])
    tr = reframer.compute_track(blip, [], 0, 10, SRC_W, SRC_H, 30, "split")
    assert set(tr.layout) == {1}


def test_split_never_shows_same_person_twice():
    # uma pessoa só, andando pela cena (vira 2 clusters próximos) e com detecção duplicada
    drift = faces_for(10, lambda t: [face(0.4 + 0.02 * t)] + ([face(0.41 + 0.02 * t, size=0.14)] if t > 5 else []))
    tr = reframer.compute_track(drift, [], 0, 10, SRC_W, SRC_H, 30, "split")
    assert set(tr.layout) == {0}
    for sp in tr.split:
        assert sp is None


def test_track_manual_keyframes():
    kf = [{"t": 0, "x": 0.3}, {"t": 2, "x": 0.7}]
    tr = reframer.compute_track({}, [], 10, 14, SRC_W, SRC_H, 10, "manual", kf)
    assert tr.cx[0] == pytest.approx(0.3)
    assert tr.cx[10] == pytest.approx(0.5, abs=0.01)  # meio: easing simétrico
    assert tr.cx[5] < 0.4  # easing: começa devagar
    assert tr.cx[-1] == pytest.approx(0.7)


def test_letterbox():
    assert reframer.letterbox(16 / 9) == (0, 0, 960, 540)
    ox, oy, w, h = reframer.letterbox(9 / 16)
    assert h == 540 and w == pytest.approx(303.75) and ox == pytest.approx((960 - 303.75) / 2) and oy == 0


def test_split_box_inside_frame():
    for fx, fy in ((0.0, 0.0), (1.0, 1.0), (0.5, 0.5)):
        x, y, w, h = reframer.split_box(1280, 720, fx, fy)
        assert 0 <= x and x + w <= 1280 and 0 <= y and y + h <= 720
        assert abs(w / h - 1080 / 960) < 0.01


# --- render ---------------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
@pytest.mark.parametrize("mode", ["auto", "split"])
def test_render_piped(tmp_path, mode):
    src = tmp_path / "fonte.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=330", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    with Session(engine) as s:
        p = Project(name=f"Reframe {mode}", source_path=str(src), origin="local_path", duration_s=6, width=1280,
                    height=720, fps=30, status="ready", stage="done")
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
        pdir = get_settings().project_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "transcript.json").write_text(json.dumps({"segments": []}))
        (pdir / "proxy.mp4").write_bytes(b"")  # a análise já existe; o proxy não é lido
        (pdir / "scenes.json").write_text(json.dumps({"cuts": [3.0]}))
        (pdir / "faces.json").write_text(json.dumps(faces_for(6, lambda t: [face(0.25), face(0.75)] if mode == "split"
                                                               else [face(0.2 if t < 3 else 0.8)])))
        clip = Clip(project_id=pid, title=f"Corte {mode}", start_s=1, end_s=5, score=70, reframe_mode=mode)
        s.add(clip)
        s.commit()
        s.refresh(clip)
        job = Job(type="render", ref_id=clip.id, status="running", uses_gpu=True)  # type: ignore[arg-type]
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)
        cid, jid = clip.id, job.id
    runner._execute(ctx)
    with Session(engine) as s:
        job = s.get(Job, jid)
        assert job and job.status == "done", job.error_detail if job else ""
        clip = s.get(Clip, cid)
        assert clip and clip.status == "rendered"
        out = Path(clip.output_path)
    info = probe.probe(out)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert abs(info.duration_s - 4.0) < 0.15
    track = json.loads((pdir / "clips" / str(cid) / "crop.json").read_text())
    assert track["mode"] == mode and track["frames"] == 120
    if mode == "auto":
        assert track["cuts"] == [2.0]
        assert track["cx"][0] == pytest.approx(0.2 if 0.2 > track["crop_w_norm"] / 2 else track["crop_w_norm"] / 2, abs=0.02)
        assert track["cx"][-1] == pytest.approx(0.8, abs=0.02)
    else:
        assert set(track["layout"]) == {1}
    # o frame renderizado mostra a região certa: no auto, metade esquerda do testsrc2 vs metade direita diferem
    frames = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-vf", "select=eq(n\\,10)+eq(n\\,100)",
                             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    a, b = np.frombuffer(frames, np.uint8).reshape(2, 1920, 1080).astype(int)
    if mode == "auto":
        assert np.abs(a - b).mean() > 5  # o crop mudou de lugar na troca de cena
    else:
        assert np.abs(a[:960] - a[960:]).mean() > 5  # metades de cima e de baixo mostram regiões diferentes
