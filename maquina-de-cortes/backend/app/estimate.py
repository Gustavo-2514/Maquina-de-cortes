"""Estimativa de tempo da análise (antes de começar), a partir do hardware e do que já está em cache.

Fatores medidos numa RTX 3050 8 GB (ver DECISIONS.md); sem GPU são estimativas conservadoras.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import UserSettings
from .services import hardware
from .services.highlighter import make_windows

# segundos de vídeo processados por segundo
PREP_SPEED = {"nvenc": 20.0, "x264": 8.0}
WHISPER_SPEED = {  # (gpu, cpu)
    "tiny": (40.0, 8.0), "base": (30.0, 5.0), "small": (20.0, 2.5), "medium": (12.0, 0.8),
    "large-v3": (6.5, 0.35), "turbo": (14.0, 1.0), "large-v3-turbo": (14.0, 1.0),
}
MODEL_LOAD_S = 12
LLM_WINDOW_S = {"gpu": 30.0, "cpu": 150.0}


def estimate(project_dir: Path, duration: float, language: str, us: UserSettings) -> dict:
    hw = hardware.detect_hardware()
    from .services.transcriber import resolve_config

    model, device, _compute = resolve_config(us)
    encoder = "nvenc" if (us.encoder == "nvenc" or (us.encoder == "auto" and hw.nvenc)) else "x264"

    prep_cached = all((project_dir / f).exists() for f in ("proxy.mp4", "audio.wav", "waveform.json"))
    tr_path = project_dir / "transcript.json"
    tr_cached = False
    if tr_path.exists():
        try:
            tr_cached = json.loads(tr_path.read_text(encoding="utf-8")).get("requested_language", "auto") == (language or "auto")
        except ValueError:
            pass

    gpu_s, cpu_s = WHISPER_SPEED.get(model, (8.0, 1.0))
    speed = gpu_s if device == "cuda" else cpu_s
    llm_gpu = (hw.vram_mb or 0) >= 6000
    stages = [
        {"key": "prep", "label": "Preparar vídeo", "cached": prep_cached,
         "seconds": 0 if prep_cached else 5 + duration / PREP_SPEED[encoder]},
        {"key": "transcribe", "label": f"Transcrever (Whisper {model}, {'GPU' if device == 'cuda' else 'CPU'})",
         "cached": tr_cached, "seconds": 0 if tr_cached else MODEL_LOAD_S + duration / speed},
        {"key": "analyze", "label": "Encontrar cortes (IA)", "cached": False,
         "seconds": len(make_windows(duration)) * LLM_WINDOW_S["gpu" if llm_gpu else "cpu"] + 10},
    ]
    for st in stages:
        st["seconds"] = round(st["seconds"])
    return {"total_seconds": sum(s["seconds"] for s in stages), "stages": stages, "gpu": device == "cuda"}


def estimate_claude(project_dir: Path, duration: float, num_clips: int, template_key: str) -> dict:
    """Custo estimado da análise com cada modelo do Claude (US$). Usa a transcrição real quando já existe;
    senão, uma média por segundo de vídeo (arredondada para cima)."""
    from .services import claude
    from .services.highlighter import build_messages, transcript_lines
    from .services.templates import get_template

    template = get_template(template_key)
    windows = make_windows(duration)
    factor = 2.5 if template.heuristic == "reactions" else 1.5
    prompt_chars: float | None = None
    tr_path = project_dir / "transcript.json"
    if tr_path.exists():
        try:
            tr = json.loads(tr_path.read_text(encoding="utf-8"))
            prompt_chars = float(sum(
                len(m["content"]) for t0, t1 in windows
                for m in build_messages(transcript_lines(tr, t0, t1), t0, t1, 3, 60, 90, template.prompt)))
        except (ValueError, KeyError):
            prompt_chars = None
    per_window, chars = claude.windows_cost_inputs(duration, num_clips, factor, len(windows), prompt_chars)
    if prompt_chars is not None:
        chars = prompt_chars  # já inclui as instruções de cada chamada
    return {"from_transcript": prompt_chars is not None, "prices_as_of": claude.PRICES_AS_OF,
            "models": [{**claude.estimate_analysis(m, len(windows), per_window, chars), "label": claude.MODEL_LABELS[m]}
                       for m in claude.PRICES]}
