"""ffprobe → duração, resolução, fps, áudio (seção 8.2)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class ProbeError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


@dataclass
class ProbeResult:
    duration_s: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    has_video: bool
    has_audio: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    num, _, den = rate.partition("/")
    try:
        v = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return round(v, 3) if 0 < v < 1000 else None


def probe(path: Path) -> ProbeResult:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ProbeError("Não foi possível executar o ffprobe.", str(e)) from e
    if r.returncode != 0:
        raise ProbeError("Arquivo de vídeo inválido ou corrompido.", r.stderr[-2000:])
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    # capas embutidas (mp3/m4a) aparecem como vídeo com attached_pic
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = data.get("format", {}).get("duration") or (video or audio or {}).get("duration")
    try:
        duration = float(dur)
    except (TypeError, ValueError):
        raise ProbeError("Não foi possível ler a duração do vídeo.", r.stdout[-1000:]) from None
    return ProbeResult(
        duration_s=duration,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")) if video else None,
        video_codec=video.get("codec_name") if video else None,
        has_video=video is not None,
        has_audio=audio is not None,
    )
