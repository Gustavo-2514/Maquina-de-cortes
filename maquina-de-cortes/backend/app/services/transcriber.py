"""Transcrição com faster-whisper e timestamps por palavra (seção 8.3)."""

from __future__ import annotations

import gc
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..config import UserSettings
from . import hardware

log = logging.getLogger(__name__)

_model: Any = None
_model_key: tuple[str, str, str] | None = None

# pontuação que o Whisper às vezes devolve como "palavra" separada
_PUNCT_ONLY = re.compile(r"^[\s.,!?;:…\"'”’)\]»-]+$")


def resolve_config(us: UserSettings) -> tuple[str, str, str]:
    """(modelo, device, compute_type) a partir das Configurações; 'auto' = pelo hardware."""
    rec = hardware.recommended_defaults(hardware.detect_hardware())["whisper"]
    device = rec["device"] if us.whisper_device == "auto" else us.whisper_device
    if device == "cuda" and not hardware.cuda_available()[0]:
        device = "cpu"
    model = us.whisper_model if us.whisper_model != "auto" else (rec["model"] if device == rec["device"] else "small")
    if us.whisper_compute_type != "auto":
        compute = us.whisper_compute_type
    elif device == "cpu":
        compute = "int8"
    else:
        compute = rec["compute_type"] if rec["device"] == "cuda" else "float16"
    return model, device, compute


def get_model(model: str, device: str, compute: str):
    """Modelo em cache no worker entre jobs; recria se a configuração mudar."""
    global _model, _model_key
    key = (model, device, compute)
    if _model is not None and _model_key == key:
        return _model
    release_model()
    from faster_whisper import WhisperModel

    log.info("carregando Whisper %s (%s, %s)", *key)
    _model = WhisperModel(model, device=device, compute_type=compute)
    _model_key = key
    return _model


def release_model() -> None:
    """Libera VRAM (necessário antes de chamar o Ollama numa GPU < 10 GB)."""
    global _model, _model_key
    if _model is not None:
        log.info("liberando Whisper da memória")
        _model = None
        _model_key = None
        gc.collect()


def unload_ollama(url: str) -> None:
    """Descarrega modelos do Ollama da VRAM (o qwen2.5:7b + Whisper large-v3 não cabem em 8 GB)."""
    base = url.rstrip("/")
    try:
        running = httpx.get(f"{base}/api/ps", timeout=3).json().get("models", [])
        for m in running:
            httpx.post(f"{base}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
            log.info("Ollama: modelo %s descarregado da VRAM", m["name"])
    except (httpx.HTTPError, ValueError, KeyError):
        pass  # Ollama desligado: nada a liberar


def postprocess_words(words: list[dict]) -> list[dict]:
    """Remove palavras de duração 0 e junta pontuação solta à palavra anterior."""
    out: list[dict] = []
    for w in words:
        text = w["w"].strip()
        if not text:
            continue
        if _PUNCT_ONLY.match(text) and out:
            out[-1]["w"] += text
            out[-1]["e"] = max(out[-1]["e"], w["e"])
            continue
        if w["e"] - w["s"] <= 0:
            continue
        out.append({**w, "w": text})
    return out


def transcribe(
    audio_path: Path,
    out_path: Path,
    duration_s: float,
    language: str | None,
    us: UserSettings,
    on_progress: Callable[[float, str], None],
    is_canceled: Callable[[], bool],
) -> dict:
    model_name, device, compute = resolve_config(us)
    if device == "cuda":
        unload_ollama(us.ollama_url)
    on_progress(0, f"Carregando Whisper {model_name} ({device})…")
    try:
        model = get_model(model_name, device, compute)
    except Exception as e:  # noqa: BLE001
        if device != "cuda":
            raise
        log.warning("falha ao carregar na GPU (%s); usando CPU", e)
        model_name, device, compute = "small", "cpu", "int8"
        model = get_model(model_name, device, compute)

    segments_iter, info = model.transcribe(
        str(audio_path), language=language, word_timestamps=True,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}, beam_size=5,
    )
    segments: list[dict] = []
    for seg in segments_iter:  # gerador: a transcrição acontece aqui
        if is_canceled():
            raise InterruptedError()
        words = postprocess_words([
            {"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}
            for w in (seg.words or [])
        ])
        if words:
            segments.append({"id": len(segments), "start": round(seg.start, 3), "end": round(seg.end, 3),
                             "text": seg.text.strip(), "words": words})
        on_progress(min(99.0, 100 * seg.end / max(duration_s, 0.001)),
                    f"Transcrevendo… {_fmt(seg.end)} de {_fmt(duration_s)}")

    result = {"language": info.language, "language_probability": round(info.language_probability, 3),
              "model": model_name, "device": device, "segments": segments}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    return result


def _fmt(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
