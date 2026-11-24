"""Render final 9:16 (seção 8.7): corte preciso + enquadramento + legenda ASS + loudnorm + encoder."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
MAX_BITRATE = "8M"  # teto: a fonte costuma ser ≤ 1080p ampliada no crop; acima disso é desperdício
RENDER_VERSION = 4  # mude ao alterar o pipeline de render → invalida o cache dos MP4s


@dataclass
class RenderSpec:
    source: Path
    start_s: float
    end_s: float
    src_w: int
    src_h: int
    src_fps: float | None
    mode: str = "center"  # center | blur_fit (só filtros); auto/split/manual usam o reframer (pipe)
    encoder: str = "x264"  # nvenc | x264
    normalize_audio: bool = True
    ass_file: str | None = "captions.ass"  # relativo ao cwd do ffmpeg (pasta do corte)
    fonts_dir: Path = FONTS_DIR
    has_audio: bool = True
    quality: str = "normal"  # high | normal | small
    gameplay: dict | None = None  # caixas normalizadas {"cam", "game", "top_ratio"} (modo gameplay)

    @property
    def duration(self) -> float:
        return round(self.end_s - self.start_s, 3)

    @property
    def fps(self) -> float:
        """fps da fonte se ≤ 60, senão 30."""
        f = self.src_fps or 30
        return round(f, 3) if 0 < f <= 60 else 30


def filter_escape(value: str) -> str:
    """Escapa um valor de opção dentro de um filtergraph (\\ : ' , ; [ ])."""
    return re.sub(r"([\\:',;\[\]])", r"\\\1", value)


def even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def center_crop_box(w: int, h: int) -> tuple[int, int, int, int]:
    """Maior retângulo 9:16 centralizado que cabe no quadro (cw, ch, x, y)."""
    if w / h > 9 / 16:  # mais largo que 9:16 → corta as laterais
        cw, ch = even(h * 9 / 16), even(h)
    else:  # mais estreito/alto → corta em cima e embaixo
        cw, ch = even(w), even(w * 16 / 9)
    return cw, ch, (w - cw) // 2 // 2 * 2, (h - ch) // 2 // 2 * 2


def _px_box(box: list[float], w: int, h: int) -> tuple[int, int, int, int]:
    """Caixa normalizada → (w, h, x, y) em pixels pares, dentro do quadro."""
    bw, bh = even(box[2] * w), even(box[3] * h)
    bw, bh = min(bw, w // 2 * 2), min(bh, h // 2 * 2)
    x = min(max(0, int(box[0] * w) // 2 * 2), w - bw)
    y = min(max(0, int(box[1] * h) // 2 * 2), h - bh)
    return bw, bh, x, y


def video_filter(spec: RenderSpec) -> str:
    tail = f"fps={spec.fps},format=yuv420p"
    if spec.ass_file:
        tail += f",ass={filter_escape(spec.ass_file)}:fontsdir={filter_escape(str(spec.fonts_dir))}"
    if spec.mode == "gameplay" and spec.gameplay and spec.gameplay.get("cam"):
        g = spec.gameplay
        top_h = even(g["top_ratio"] * OUT_H)
        bot_h = OUT_H - top_h
        cw, ch, cx, cy = _px_box(g["cam"], spec.src_w, spec.src_h)
        gw, gh, gx, gy = _px_box(g["game"], spec.src_w, spec.src_h)
        return (
            "[0:v]split=2[camsrc][gamesrc];"
            f"[camsrc]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{top_h}:flags=lanczos,setsar=1[top];"
            f"[gamesrc]crop={gw}:{gh}:{gx}:{gy},scale={OUT_W}:{bot_h}:flags=lanczos,setsar=1[bot];"
            f"[top][bot]vstack=inputs=2,{tail}[v]"
        )
    if spec.mode in ("blur_fit", "gameplay"):  # gameplay sem webcam: jogo inteiro sobre fundo borrado
        return (
            "[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={OUT_W // 4}:{OUT_H // 4}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W // 4}:{OUT_H // 4},gblur=sigma=12,scale={OUT_W}:{OUT_H},eq=brightness=-0.08[bg];"
            f"[fgsrc]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,{tail}[v]"
        )
    cw, ch, x, y = center_crop_box(spec.src_w, spec.src_h)
    return f"[0:v]crop={cw}:{ch}:{x}:{y},scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1,{tail}[v]"


QUALITY = {  # (cq do NVENC, crf do x264, teto de bitrate)
    "high": (19, 18, "12M"),
    "normal": (21, 20, MAX_BITRATE),
    "small": (25, 24, "4M"),
}


def encoder_args(encoder: str, fps: float, quality: str = "normal") -> list[str]:
    g = str(max(1, round(fps * 2)))
    cq, crf, maxrate = QUALITY.get(quality, QUALITY["normal"])
    bufsize = f"{int(maxrate[:-1]) * 2}M"
    if encoder == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                "-maxrate", maxrate, "-bufsize", bufsize, "-profile:v", "high", "-g", g]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-maxrate", maxrate, "-bufsize", bufsize,
            "-profile:v", "high", "-g", g]


def piped_encode_args(spec: RenderSpec) -> list[str]:
    """Argumentos do encoder quando o vídeo chega cru pelo stdin (entrada 0) e o áudio vem da fonte (entrada 1)."""
    tail = "setsar=1,format=yuv420p"
    if spec.ass_file:
        tail += f",ass={filter_escape(spec.ass_file)}:fontsdir={filter_escape(str(spec.fonts_dir))}"
    fc = f"[0:v]scale={OUT_W}:{OUT_H}:flags=lanczos,{tail}[v]"
    maps = ["-map", "[v]"]
    if spec.has_audio:
        afilter = f"{LOUDNORM},aresample=48000" if spec.normalize_audio else "aresample=48000"
        fc += f";[1:a:0]{afilter}[a]"
        maps += ["-map", "[a]"]
    args = ["-filter_complex", fc, *maps, *encoder_args(spec.encoder, spec.fps, spec.quality), "-pix_fmt", "yuv420p"]
    if spec.has_audio:
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    return [*args, "-movflags", "+faststart", "-t", f"{spec.duration:.3f}"]


def build_command(spec: RenderSpec, output: Path) -> list[str]:
    """Argumentos do ffmpeg (sem o binário). `-ss` antes do `-i` + re-encode = corte preciso e rápido,
    e os timestamps da saída começam em 0 — exatamente os tempos relativos do .ass."""
    fc = video_filter(spec)
    args = ["-ss", f"{spec.start_s:.3f}", "-t", f"{spec.duration:.3f}", "-i", str(spec.source)]
    maps = ["-map", "[v]"]
    if spec.has_audio:
        afilter = f"{LOUDNORM},aresample=48000" if spec.normalize_audio else "aresample=48000"
        fc += f";[0:a:0]{afilter}[a]"
        maps += ["-map", "[a]"]
    args += ["-filter_complex", fc, *maps, *encoder_args(spec.encoder, spec.fps, spec.quality), "-pix_fmt", "yuv420p"]
    if spec.has_audio:
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    args += ["-movflags", "+faststart", "-t", f"{spec.duration:.3f}", str(output)]
    return args


def slugify(text: str, max_len: int = 50) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:max_len].rstrip("-") or "corte"


def output_name(score: float, title: str) -> str:
    return f"{int(round(score)):02d}_{slugify(title)}.mp4"


def preview_args(video: Path, at_s: float, out: Path) -> list[str]:
    return ["-ss", f"{max(0.0, at_s):.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=540:-2:out_range=full,format=yuvj420p", "-q:v", "3",
            str(out)]
