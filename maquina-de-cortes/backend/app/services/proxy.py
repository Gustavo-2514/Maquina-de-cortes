"""Proxy 540p para o editor, áudio 16 kHz para o Whisper, picos da forma de onda e thumbnails (seção 8.2)."""

from __future__ import annotations

import json
import math
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .ffmpeg import run_ffmpeg

PEAKS_PER_SECOND = 100
THUMB_EVERY_S = 10


def proxy_args(source: Path, out: Path, fps: float | None, encoder: str, has_audio: bool) -> list[str]:
    g = str(max(1, round(fps or 30)))  # keyframe a cada ~1 s → seek rápido no editor
    v = (["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "30", "-b:v", "0"]
         if encoder == "nvenc" else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"])
    a = ["-c:a", "aac", "-b:a", "96k", "-ac", "2"] if has_audio else ["-an"]
    return ["-i", str(source), "-map", "0:v:0", *(["-map", "0:a:0"] if has_audio else []),
            "-vf", "scale=-2:'min(540,ih)':flags=bicubic,format=yuv420p", *v, "-g", g, "-keyint_min", g,
            *a, "-movflags", "+faststart", str(out)]


def audio_args(source: Path, out: Path) -> list[str]:
    return ["-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]


def thumbs_args(source: Path, out_dir: Path) -> list[str]:
    # select (não fps=1/N): sempre pega o quadro 0 — com fps=1/10 um vídeo < 10 s não gerava miniatura nenhuma.
    # out_range=full: o encoder JPEG do FFmpeg 8 recusa YUV "limited range".
    sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{THUMB_EVERY_S})'"
    return ["-i", str(source), "-map", "0:v:0", "-vf", f"{sel},scale=-2:90:out_range=full,format=yuvj420p",
            "-fps_mode", "vfr", "-q:v", "5", str(out_dir / "%05d.jpg")]


def compute_peaks(wav_path: Path, out: Path, per_second: int = PEAKS_PER_SECOND) -> int:
    """Pico absoluto normalizado (0-1) por bloco — formato aceito pelo wavesurfer (`peaks`)."""
    peaks: list[float] = []
    with wave.open(str(wav_path), "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        if width != 2:
            raise ValueError("WAV precisa ser PCM 16 bits")
        block = max(1, rate // per_second)
        chunk_blocks = per_second * 60  # lê 1 min por vez (memória constante)
        while True:
            raw = w.readframes(block * chunk_blocks)
            if not raw:
                break
            data = np.frombuffer(raw, dtype="<i2")
            if channels > 1:
                data = data.reshape(-1, channels).mean(axis=1)
            n = math.ceil(len(data) / block)
            pad = n * block - len(data)
            if pad:
                data = np.concatenate([data, np.zeros(pad, dtype=data.dtype)])
            peaks.extend(np.abs(data.reshape(n, block).astype(np.int32)).max(axis=1).tolist())
    top = max(peaks) if peaks else 1
    norm = [round(p / top, 3) if top else 0 for p in peaks]
    out.write_text(json.dumps({"rate": per_second, "length": len(norm), "peaks": norm}), encoding="utf-8")
    return len(norm)


def staged(steps: list[tuple[str, float]], report: Callable[[float, str], None]):
    """Converte progresso de cada etapa (0-100) em progresso global ponderado."""
    total = sum(w for _, w in steps)
    offsets, acc = {}, 0.0
    for name, w in steps:
        offsets[name] = (acc, w)
        acc += w

    def for_step(name: str, label: str) -> Callable[[float], None]:
        start, w = offsets[name]
        return lambda pct: report(100 * (start + w * pct / 100) / total, label)

    return for_step
