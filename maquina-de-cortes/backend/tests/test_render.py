"""Fase 4: legendas ASS, comando do ffmpeg, migração e render real (vídeo sintético)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine, init_db
from app.main import app
from app.models import CaptionStyle, Clip, Job, Project
from app.services import captions, probe, renderer
from app.services.caption_styles import BUILTIN
from app.worker import runner, tasks

init_db()


def W(text, s, e):
    return {"w": text, "s": s, "e": e, "p": 0.9}


# --- captions -------------------------------------------------------------------
def test_ass_colors_are_bgr():
    assert captions.ass_color("#FFE600") == "&H0000E6FF"
    assert captions.ass_color("#112233", 0x80) == "&H80332211"
    assert captions.inline_color("#39FF14") == "&H14FF39&"


def test_ass_time():
    assert captions.ass_time(0) == "0:00:00.00"
    assert captions.ass_time(61.236) == "0:01:01.24"
    assert captions.ass_time(3725.5) == "1:02:05.50"


def test_clip_words_relative_and_overrides():
    words = [W("antes", 9.0, 9.8), W("Olá", 10.0, 10.4), W("mundo.", 10.5, 11.0), W("depois", 20.5, 21)]
    out = captions.clip_words(words, 10.0, 20.0, {"10.500": "planeta."})
    assert [w["w"] for w in out] == ["Olá", "planeta."]
    assert out[0]["s"] == 0.0 and out[1]["s"] == 0.5 and out[1]["e"] == 1.0
    # palavra apagada pelo usuário (override vazio) some da legenda
    assert [w["w"] for w in captions.clip_words(words, 10, 20, {"10.000": ""})] == ["mundo."]


def test_group_lines_rules():
    ws = [W("um", 0, .2), W("dois", .25, .4), W("três", .45, .6), W("quatro.", .65, .8), W("cinco", .85, 1),
          W("seis", 2.0, 2.2), W("superextraordinariamente", 2.25, 3)]
    lines = [[w["w"] for w in line] for line in captions.group_lines(ws, 3)]
    # 3 por linha; ponto quebra; pausa > 0,35 s quebra; linha > 18 caracteres quebra
    assert lines == [["um", "dois", "três"], ["quatro."], ["cinco"], ["seis"], ["superextraordinariamente"]]


def test_build_ass_highlight_and_karaoke():
    ws = [W("olá", 0.0, 0.4), W("mundo", 0.5, 0.9), W("aqui", 2.0, 2.4)]
    st = captions.Style(words_per_line=2, uppercase=True, highlight_color="#FFE600", animation="highlight")
    ass = captions.build_ass(ws, st, duration=3.0, title="Meu {título}")
    dialogs = [l for l in ass.splitlines() if l.startswith("Dialogue: 0")]
    assert len(dialogs) == 3  # um evento por palavra
    assert "{\\c&H00E6FF&}OLÁ" in dialogs[0] and "MUNDO" in dialogs[0]
    assert dialogs[0].split(",")[1] == "0:00:00.00" and dialogs[1].split(",")[2] == "0:00:01.15"  # segura 0,25 s
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Meu (título)" in ass  # chaves escapadas
    k = captions.build_ass(ws, captions.Style(words_per_line=2, animation="karaoke"), 3.0)
    second = [l for l in k.splitlines() if l.startswith("Dialogue: 0")][1]
    assert second.count("\\c&H00E6FF&") == 2  # palavras já faladas continuam coloridas
    none = captions.build_ass(ws, captions.Style(words_per_line=2, animation="none"), 3.0)
    assert len([l for l in none.splitlines() if l.startswith("Dialogue")]) == 2  # um por linha
    pop = captions.build_ass(ws, captions.Style(animation="pop"), 3.0)
    assert "\\fscx118" in pop and "\\t(0,120" in pop


# --- renderer -------------------------------------------------------------------
def test_center_crop_box():
    assert renderer.center_crop_box(1920, 1080) == (606, 1080, 656, 0)
    cw, ch, x, y = renderer.center_crop_box(1080, 1920)  # já vertical: usa o quadro todo
    assert (cw, ch, x, y) == (1080, 1920, 0, 0)
    cw, ch, _x, y = renderer.center_crop_box(720, 1600)  # mais alto que 9:16: corta em cima/embaixo
    assert cw == 720 and ch == 1280 and y == 160


def test_build_command():
    spec = renderer.RenderSpec(source=Path("/v/meu vídeo.mp4"), start_s=12.3456, end_s=42.0, src_w=1920, src_h=1080,
                               src_fps=59.94, encoder="nvenc", fonts_dir=Path("/f:onts"))
    args = renderer.build_command(spec, Path("out.mp4"))
    assert args[:6] == ["-ss", "12.346", "-t", "29.654", "-i", "/v/meu vídeo.mp4"]
    fc = args[args.index("-filter_complex") + 1]
    assert "crop=606:1080:656:0,scale=1080:1920" in fc and "fps=59.94" in fc
    assert "ass=captions.ass:fontsdir=/f\\:onts" in fc  # ':' escapado no filtergraph
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in fc
    assert "h264_nvenc" in args and "-cq" in args and "+faststart" in args
    assert args[args.index("-maxrate") + 1] == renderer.MAX_BITRATE
    spec.encoder, spec.mode, spec.normalize_audio, spec.src_fps = "x264", "blur_fit", False, 120
    args = renderer.build_command(spec, Path("out.mp4"))
    fc = args[args.index("-filter_complex") + 1]
    assert "gblur" in fc and "overlay" in fc and "loudnorm" not in fc and "fps=30" in fc
    assert "libx264" in args and "-crf" in args


def test_output_name():
    assert renderer.output_name(87.4, "Não escute seus pais!") == "87_nao-escute-seus-pais.mp4"
    assert renderer.output_name(5, "???") == "05_corte.mp4"


# --- migração ---------------------------------------------------------------------
def test_migration_adds_missing_columns(tmp_path, monkeypatch):
    import sqlite3

    from sqlmodel import create_engine

    from app import db

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE clip (id INTEGER PRIMARY KEY, project_id INTEGER, start_s FLOAT, end_s FLOAT)")
    con.execute("INSERT INTO clip (project_id, start_s, end_s) VALUES (1, 0, 10)")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{path}"))
    db._add_missing_columns()
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(clip)")}
    assert {"error", "rendered_at", "title", "status", "score"} <= cols
    assert con.execute("SELECT status, error, score FROM clip").fetchone() == ("suggested", "", 0)


def test_builtin_styles_seeded():
    with Session(engine) as s:
        keys = {c.key for c in s.exec(select(CaptionStyle).where(CaptionStyle.is_builtin == True)).all()}  # noqa: E712
    assert keys == {b["key"] for b in BUILTIN}


# --- render de verdade ------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_render_end_to_end(tmp_path):
    src = tmp_path / "fonte.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "8", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    with Session(engine) as s:
        p = Project(name="Render teste", source_path=str(src), origin="local_path", duration_s=8, width=1280,
                    height=720, fps=30, status="ready", stage="done")
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
        pdir = get_settings().project_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "transcript.json").write_text(json.dumps({"segments": [{"id": 0, "start": 1, "end": 4, "text": "",
            "words": [W("Olá", 1.0, 1.5), W("pessoal,", 1.6, 2.2), W("tudo", 2.4, 2.8), W("certo?", 2.9, 3.6)]}]}))
        clips = [Clip(project_id=pid, title="Corte A", start_s=1.0, end_s=5.0, score=87, reframe_mode="center"),
                 Clip(project_id=pid, title="Corte B", start_s=2.0, end_s=6.0, score=64, reframe_mode="blur_fit",
                      title_overlay="Título no topo"),
                 Clip(project_id=pid, title="Descartado", start_s=0, end_s=3, status="discarded")]
        s.add_all(clips)
        s.commit()
        ids = [c.id for c in clips]

    with TestClient(app) as c:
        assert c.get(f"/api/clips/{ids[0]}/file").status_code == 404
        jobs = c.post(f"/api/projects/{pid}/render-all").json()
        assert sorted(j["ref_id"] for j in jobs) == sorted(ids[:2])  # descartado fica de fora
        # pedir de novo não duplica jobs
        assert {j["id"] for j in c.post(f"/api/projects/{pid}/render-all").json()} == {j["id"] for j in jobs}

    for j in jobs:
        with Session(engine) as s:
            job = s.get(Job, j["id"])
            job.status = "running"  # type: ignore[union-attr]
            s.add(job)
            s.commit()
            s.refresh(job)
            ctx = tasks.JobContext(job)  # type: ignore[arg-type]
        runner._execute(ctx)
        with Session(engine) as s:
            job = s.get(Job, j["id"])
            assert job and job.status == "done", job.error_detail if job else ""

    with TestClient(app) as c:
        for cid, mode in zip(ids[:2], ("center", "blur_fit")):
            clip = c.get(f"/api/clips/{cid}").json()
            assert clip["status"] == "rendered" and clip["rendered_at"]
            out = Path(clip["output_path"])
            info = probe.probe(out)
            assert (info.width, info.height) == (1080, 1920), mode
            assert info.has_audio and abs(info.duration_s - 4.0) < 0.15
            assert (pdir / "clips" / str(cid) / "preview.jpg").exists()
            assert (pdir / "clips" / str(cid) / "captions.ass").exists()
        a = Path(c.get(f"/api/clips/{ids[0]}").json()["output_path"])
        assert a.name == "87_corte-a.mp4"
        r = c.get(f"/api/clips/{ids[0]}/file", headers={"Range": "bytes=0-9"})
        assert r.status_code == 206
        r = c.get(f"/api/clips/{ids[0]}/file", params={"download": True})
        assert "attachment" in r.headers["content-disposition"]

        # sem mudanças → cache; editar → volta a "edited" e o render seguinte refaz
        mtime = a.stat().st_mtime
        job = c.post(f"/api/clips/{ids[0]}/render").json()
        _run(job["id"])
        assert a.stat().st_mtime == mtime
        assert c.patch(f"/api/clips/{ids[0]}", json={"title": "Novo nome"}).json()["status"] == "edited"
        _run(c.post(f"/api/clips/{ids[0]}/render").json()["id"])
        new = Path(c.get(f"/api/clips/{ids[0]}").json()["output_path"])
        assert new.name == "87_novo-nome.mp4" and new.exists() and not a.exists()
        c.delete(f"/api/projects/{pid}")


def _run(job_id: int) -> None:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        job.status = "running"  # type: ignore[union-attr]
        s.add(job)
        s.commit()
        s.refresh(job)
        ctx = tasks.JobContext(job)  # type: ignore[arg-type]
    runner._execute(ctx)
    with Session(engine) as s:
        assert s.get(Job, job_id).status == "done"  # type: ignore[union-attr]


def test_caption_styles_api():
    with TestClient(app) as c:
        styles = c.get("/api/caption-styles").json()
        hormozi = next(s for s in styles if s["key"] == "hormozi")
        assert hormozi["is_builtin"] and hormozi["highlight_color"] == "#FFE600"
        assert c.patch(f"/api/caption-styles/{hormozi['id']}", json={"font_size": 50}).status_code == 409
        new = c.post("/api/caption-styles", json={"name": "Meu", "highlight_color": "#FF00AA", "words_per_line": 3}).json()
        assert c.patch(f"/api/caption-styles/{new['id']}", json={"font_size": 70}).json()["font_size"] == 70
        assert c.post("/api/caption-styles", json={"name": "x", "primary_color": "vermelho"}).status_code == 422
        assert c.delete(f"/api/caption-styles/{new['id']}").json()["ok"]


def test_shared_caption_fixture():
    """Mesmos casos rodam no vitest (frontend/src/lib/captions.test.ts): preview == render."""
    data = json.loads((Path(__file__).parent / "fixtures" / "captions_cases.json").read_text())
    for case in data["cases"]:
        lines = captions.group_lines(case["words"], case["words_per_line"])
        assert [[w["w"] for w in line] for line in lines] == case["lines"], case["name"]
        spans = captions.caption_spans(case["words"], case["words_per_line"], case["animation"], case["duration"])
        assert spans == case["spans"], case["name"]


def test_style_merge_and_overrides():
    base = captions.Style()
    m = base.merged({"font_size": "120", "highlight_color": "#00FF00", "words_per_line": 9, "animation": "xx",
                     "outline_color": "verde", "desconhecido": 1})
    assert m.font_size == 120 and m.highlight_color == "#00FF00" and m.words_per_line == 4
    assert m.animation == base.animation and m.outline_color == base.outline_color
    ov = captions.parse_overrides(json.dumps({"words": {"1.000": "oi"}, "style": {"uppercase": False}, "title_until": 3}))
    assert ov.words == {"1.000": "oi"} and ov.style == {"uppercase": False} and ov.title_until == 3
    assert captions.parse_overrides('{"1.000": "oi"}').words == {"1.000": "oi"}  # formato antigo
    assert captions.parse_overrides("lixo").words == {}
    ass = captions.build_ass([W("oi", 0, 1)], base, 10, title="T", title_until=3)
    assert "Dialogue: 1,0:00:00.00,0:00:03.00,Title" in ass


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg ausente")
def test_editor_changes_reach_final_mp4(tmp_path):
    """Critério da Fase 6: início/fim, estilo e palavra corrigida no editor → MP4 final."""
    src = tmp_path / "fonte.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=500", "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    with Session(engine) as s:
        p = Project(name="Editor", source_path=str(src), origin="local_path", duration_s=10, width=1280, height=720,
                    fps=30, status="ready", stage="done")
        s.add(p)
        s.commit()
        s.refresh(p)
        pid = p.id
        pdir = get_settings().project_dir(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "transcript.json").write_text(json.dumps({"segments": [{"id": 0, "start": 1, "end": 8, "text": "",
            "words": [W("um", 1.0, 1.4), W("dois", 1.5, 2.0), W("tres", 3.0, 3.4), W("quatro", 6.0, 6.5)]}]}))
        c = Clip(project_id=pid, title="Ed", start_s=0.5, end_s=4.5, score=50, reframe_mode="center")
        s.add(c)
        s.commit()
        cid = c.id
    with TestClient(app) as cl:
        ov = {"words": {"3.000": "três"}, "style": {"highlight_color": "#FF0000", "uppercase": False}}
        r = cl.patch(f"/api/clips/{cid}", json={"start_s": 0.8, "end_s": 7.0, "caption_overrides_json": json.dumps(ov),
                                                 "export_json": json.dumps({"quality": "small"})})
        assert r.status_code == 200 and r.json()["status"] == "edited"
        _run(cl.post(f"/api/clips/{cid}/render").json()["id"])
        clip = cl.get(f"/api/clips/{cid}").json()
    ass = (pdir / "clips" / str(cid) / "captions.ass").read_text()
    assert "três" in ass and "tres" not in ass  # palavra corrigida
    assert "{\\c&H0000FF&}" in ass  # destaque vermelho (BGR)
    assert "quatro" in ass  # fim estendido inclui a palavra em 6 s
    assert "UM" not in ass and "um" in ass  # uppercase desligado
    info = probe.probe(Path(clip["output_path"]))
    assert abs(info.duration_s - 6.2) < 0.15  # 0.8 → 7.0
    cl2 = TestClient(app)
    cl2.delete(f"/api/projects/{pid}")
