from fastapi.testclient import TestClient

from app.main import app
from app.services.hardware import Hardware, recommended_defaults


def test_health_and_check():
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"ok": True}
        r = c.get("/api/system/check")
        assert r.status_code == 200
        keys = {i["key"] for i in r.json()["items"]}
        assert {"ffmpeg", "ffprobe", "libass", "ollama", "cuda", "nvenc", "disk"} <= keys


def test_settings_roundtrip():
    with TestClient(app) as c:
        s = c.get("/api/system/settings").json()
        s["ollama_model"] = "qwen2.5:3b"
        assert c.put("/api/system/settings", json=s).status_code == 200
        assert c.get("/api/system/settings").json()["ollama_model"] == "qwen2.5:3b"


def test_recommended_defaults():
    assert recommended_defaults(Hardware())["whisper"]["device"] == "cpu"
    rec = recommended_defaults(Hardware(cuda=True, vram_mb=8192, nvenc=True))
    assert rec["whisper"]["model"] == "large-v3" and rec["encoder"] == "nvenc"
    assert recommended_defaults(Hardware(cuda=True, vram_mb=4096))["whisper"]["compute_type"] == "int8_float16"


def test_api_unknown_route_is_404():
    with TestClient(app) as c:
        assert c.get("/api/nao-existe").status_code == 404
