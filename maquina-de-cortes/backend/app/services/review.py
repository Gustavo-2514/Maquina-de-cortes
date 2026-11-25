"""Revisão visual de um corte renderizado pelo Claude (pago, opcional).

Extrai N quadros do MP4 final + a transcrição do corte e pede um checklist objetivo:
crop cortando rosto, legenda tapando algo, gancho fraco, final no meio da frase etc.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

from . import claude
from .ffmpeg import run_ffmpeg

N_FRAMES = 8
FRAME_H = 720

ISSUE_KINDS = ["enquadramento", "legenda", "gancho", "final", "imagem", "audio", "outro"]

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "warn", "bad"]},
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t": {"type": "number"},
                    "kind": {"type": "string", "enum": ISSUE_KINDS},
                    "severity": {"type": "string", "enum": ["leve", "grave"]},
                    "text": {"type": "string"},
                },
                "required": ["t", "kind", "severity", "text"],
            },
        },
    },
    "required": ["verdict", "summary", "issues"],
}

SYSTEM = """Você revisa cortes verticais (9:16) para TikTok/Reels/Shorts antes da publicação.
Recebe quadros do vídeo FINAL (já com legendas queimadas), cada um com o segundo em que aparece, e a fala do corte.
Aponte só problemas concretos e visíveis/legíveis nos quadros ou na fala, sem inventar:
- enquadramento: rosto cortado, pessoa fora do quadro, foco na pessoa errada, barras/bordas estranhas;
- legenda: tampando rosto ou algo importante, ilegível, cortada na borda, com erro de digitação evidente;
- gancho: os primeiros ~3 s não prendem (começa no meio de uma frase, com silêncio, saudação, contexto que falta);
- final: termina no meio de uma frase/ideia;
- imagem: tela preta, congelada, borrada demais, marca d'água de terceiros;
- audio: só se a fala indicar (ex.: transcrição vazia ou sem sentido).
verdict: "ok" = pode postar; "warn" = postável, mas vale ajustar; "bad" = precisa corrigir antes.
summary: uma frase em português. issues: no máximo 6, mais grave primeiro; t = segundo do corte.
Responda só no JSON pedido."""


def extract_frames(mp4: Path, duration: float, out_dir: Path, n: int = N_FRAMES,
                   register_process: Callable | None = None, is_canceled: Callable[[], bool] | None = None
                   ) -> list[tuple[float, Path]]:
    """N quadros espaçados (meio de cada fatia), reduzidos para 720 px de altura."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f*.jpg"):
        old.unlink()
    rate = n / max(duration, 0.5)
    run_ffmpeg(["-i", str(mp4), "-vf", f"fps={rate:.6f}:start_time=0,scale=-2:{FRAME_H}",
                "-frames:v", str(n), "-q:v", "4", str(out_dir / "f%02d.jpg")],
               register_process=register_process, is_canceled=is_canceled,
               error_message="Falha ao extrair quadros do corte")
    frames = sorted(out_dir.glob("f*.jpg"))
    return [((i + 0.5) / rate, f) for i, f in enumerate(frames)]


def build_content(frames: list[tuple[float, Path]], speech: str, title: str, duration: float) -> list[dict]:
    content: list[dict] = []
    for t, f in frames:
        content.append({"type": "text", "text": f"Quadro em {t:.1f}s:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(f.read_bytes()).decode()}})
    content.append({"type": "text", "text": f"Título do corte: {title or '(sem título)'}\nDuração: {duration:.1f}s\n"
                                            f"FALA (com segundos do corte):\n{speech or '(sem fala transcrita)'}"})
    return content


def speech_lines(words: list[dict], per_line: int = 12) -> str:
    lines = []
    for i in range(0, len(words), per_line):
        chunk = words[i:i + per_line]
        lines.append(f"[{chunk[0]['s']:.1f}s] " + " ".join(w["w"].strip() for w in chunk))
    return "\n".join(lines)


def parse(raw: str) -> dict:
    data = json.loads(raw)
    verdict = data.get("verdict") if data.get("verdict") in ("ok", "warn", "bad") else "warn"
    issues = []
    for it in data.get("issues") or []:
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        try:
            t = max(0.0, float(it.get("t", 0)))
        except (TypeError, ValueError):
            t = 0.0
        issues.append({"t": round(t, 1), "kind": it.get("kind") if it.get("kind") in ISSUE_KINDS else "outro",
                       "severity": "grave" if it.get("severity") == "grave" else "leve",
                       "text": str(it["text"]).strip()[:300]})
    return {"verdict": verdict, "summary": str(data.get("summary", "")).strip()[:300], "issues": issues[:6]}


def review(api_key: str, model: str, frames: list[tuple[float, Path]], speech: str, title: str, duration: float,
           is_canceled: Callable[[], bool] = lambda: False) -> tuple[dict, dict]:
    """→ (resultado, custo real)."""
    meter = claude.CostMeter()
    raw = claude.create(claude.make_client(api_key), model, SYSTEM, build_content(frames, speech, title, duration),
                        SCHEMA, meter, is_canceled)
    return parse(raw), meter.as_dict()
