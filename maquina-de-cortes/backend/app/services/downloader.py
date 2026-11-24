"""Download de vídeos com yt-dlp (seção 8.1)."""

from __future__ import annotations

import glob
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled

log = logging.getLogger(__name__)

FORMATS: dict[str, dict[str, Any]] = {
    "best": {"format": "bv*+ba/b", "merge_output_format": "mp4"},
    "1080p": {"format": "bv*[height<=1080]+ba/b[height<=1080]", "merge_output_format": "mp4"},
    "720p": {"format": "bv*[height<=720]+ba/b[height<=720]", "merge_output_format": "mp4"},
    "audio_mp3": {
        "format": "ba/b",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    },
}

OUTTMPL = "%(title).80s [%(id)s].%(ext)s"


class Canceled(DownloadCancelled):
    msg = "Download cancelado"


class FriendlyError(Exception):
    """Erro com mensagem em PT-BR para o usuário + detalhe técnico."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


_ERROR_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("ffmpeg", "ffprobe"), "Falha no FFmpeg ao juntar áudio e vídeo. Verifique o diagnóstico em Configurações."),
    (("private video", "video is private", "this video is private"), "Este vídeo é privado."),
    (("sign in to confirm your age", "age-restricted", "age restricted", "inappropriate for some users"),
     "Vídeo com restrição de idade. Configure um cookies.txt de uma conta logada em Configurações."),
    (("not available in your country", "geo restrict", "geo-restrict", "blocked it in your country"),
     "Vídeo bloqueado na sua região (geobloqueio)."),
    (("sign in to confirm you", "not a bot", "login required", "requires authentication", "use --cookies"),
     "O site pediu login. Configure um cookies.txt em Configurações."),
    (("video unavailable", "has been removed", "does not exist", "404", "not found"),
     "Vídeo indisponível ou removido."),
    (("members-only", "members only", "join this channel"), "Vídeo exclusivo para membros do canal."),
    (("premieres in", "live event will begin", "this live event"), "A live/estreia ainda não começou."),
    (("unsupported url",), "Link não suportado. Confira se o endereço está correto."),
    (("unable to download", "connection", "timed out", "network is unreachable", "name or service not known",
      "temporary failure in name resolution"),
     "Falha de rede ao baixar. Verifique sua conexão e tente de novo."),
    (("http error 403", "forbidden"), "O site recusou o download (403). Tente atualizar o yt-dlp em Configurações."),
]


def friendly_error(exc: BaseException) -> FriendlyError:
    detail = str(exc)
    low = detail.lower()
    for needles, msg in _ERROR_PATTERNS:
        if any(n in low for n in needles):
            return FriendlyError(msg, detail)
    return FriendlyError("Não foi possível baixar este link.", detail)


def base_opts(cookies_path: str = "") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "restrictfilenames": False,
        # YouTube exige resolver desafios em JS: habilita node (deno é o padrão do yt-dlp) se existir.
        "js_runtimes": {name: {} for name in ("deno", "node") if shutil.which(name)} or {"deno": {}},
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
    }
    if cookies_path and Path(cookies_path).is_file():
        opts["cookiefile"] = cookies_path
    return opts


def _thumb(info: dict) -> str:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = info.get("thumbnails") or []
    return thumbs[-1].get("url", "") if thumbs else ""


def _entry_url(e: dict) -> str:
    url = e.get("webpage_url") or e.get("url") or ""
    if url.startswith("http"):
        return url
    if e.get("ie_key") == "Youtube" and e.get("id"):
        return f"https://www.youtube.com/watch?v={e['id']}"
    return url


def extract_info(url: str, cookies_path: str = "") -> dict:
    """Metadados sem baixar. Playlists retornam a lista de entradas (sem resolver cada vídeo)."""
    opts = {**base_opts(cookies_path), "skip_download": True, "extract_flat": "in_playlist"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        raise friendly_error(e) from e
    if info is None:
        raise FriendlyError("Não foi possível ler este link.")

    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        entries = []
        for e in info.get("entries") or []:
            if not e:
                continue
            entries.append({
                "url": _entry_url(e),
                "title": e.get("title") or e.get("id") or "",
                "duration_s": e.get("duration"),
                "thumbnail_url": _thumb(e),
                "uploader": e.get("uploader") or e.get("channel") or "",
            })
        return {
            "kind": "playlist",
            "url": url,
            "title": info.get("title") or "Playlist",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "entries": entries,
        }

    heights = sorted({f["height"] for f in info.get("formats") or [] if f.get("height") and f.get("vcodec") != "none"})
    return {
        "kind": "video",
        "url": info.get("webpage_url") or url,
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration_s": info.get("duration"),
        "thumbnail_url": _thumb(info),
        "is_live": bool(info.get("is_live")),
        "heights": heights,
    }


@dataclass
class Progress:
    percent: float
    speed: str
    eta: str
    downloaded: int | None
    total: int | None
    phase: str  # "download" | "postprocess"


def _fmt_speed(bps: float | None) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024:
            return f"{bps:.1f} {unit}"
        bps /= 1024
    return f"{bps:.1f} TB/s"


def _fmt_eta(s: float | None) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def overall_percent(part: int, frac: float, sizes: list[int]) -> float:
    """Progresso total (0–99) de um download em partes sequenciais, ponderado pelo tamanho."""
    n = max(len(sizes), part + 1, 1)
    sz = [s if s and s > 0 else 0 for s in sizes] + [0] * (n - len(sizes))
    if all(sz) and sum(sz) > 0:
        pct = 100.0 * (sum(sz[:part]) + frac * sz[part]) / sum(sz)
    else:  # tamanhos desconhecidos: partes com peso igual
        pct = 100.0 * (part + frac) / n
    return round(min(99.0, max(0.0, pct)), 1)


def download(
    url: str,
    format_choice: str,
    out_dir: Path,
    on_progress: Callable[[Progress], None],
    is_canceled: Callable[[], bool],
    on_info: Callable[[dict], None] | None = None,
    cookies_path: str = "",
) -> Path:
    """Baixa `url` em `out_dir`. Retorna o caminho final. Lança Canceled ou FriendlyError."""
    if format_choice not in FORMATS:
        raise FriendlyError(f"Formato inválido: {format_choice}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Um vídeo DASH tem 2 streams (vídeo + áudio) baixadas em sequência: o progresso total
    # pondera cada parte pelo tamanho esperado. As partes são conhecidas após resolver os formatos.
    state: dict[str, Any] = {"format_ids": [], "sizes": [], "part": 0, "last_file": None, "tmp_files": set()}

    def hook(d: dict) -> None:
        if is_canceled():
            raise Canceled()
        if d.get("tmpfilename"):
            state["tmp_files"].add(d["tmpfilename"])
        fid = (d.get("info_dict") or {}).get("format_id")
        fname = d.get("filename")
        if fid in state["format_ids"]:
            state["part"] = state["format_ids"].index(fid)
        elif fname and fname != state["last_file"] and state["last_file"] is not None:
            state["part"] += 1
        if fname:
            state["last_file"] = fname
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0.0
            pct = overall_percent(state["part"], frac, state["sizes"])
            on_progress(Progress(pct, _fmt_speed(d.get("speed")), _fmt_eta(d.get("eta")), done, total, "download"))
        elif d["status"] == "finished":
            on_progress(Progress(overall_percent(state["part"], 1.0, state["sizes"]), "", "", None, None, "download"))

    def pp_hook(d: dict) -> None:
        if is_canceled():
            raise Canceled()
        if d.get("status") == "started":
            on_progress(Progress(99.0, "", "", None, None, "postprocess"))

    opts = {
        **base_opts(cookies_path),
        **FORMATS[format_choice],
        "outtmpl": str(out_dir / OUTTMPL),
        "paths": {"home": str(out_dir)},
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "noplaylist": True,
        "continuedl": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # 1) resolve formatos (sem baixar) → metadados e partes; 2) baixa a partir dessa info
            pre = ydl.extract_info(url, download=False)
            if pre is None:
                raise FriendlyError("O yt-dlp não retornou informações do vídeo.")
            if on_info:
                on_info(pre)
            parts = pre.get("requested_formats") or [pre]
            state["format_ids"] = [f.get("format_id") for f in parts]
            state["sizes"] = [f.get("filesize") or f.get("filesize_approx") or 0 for f in parts]
            if is_canceled():
                raise Canceled()
            info = ydl.process_ie_result(pre, download=True)
    except FriendlyError:
        raise
    except Canceled:
        _cleanup(state["tmp_files"])
        raise
    except DownloadCancelled:
        _cleanup(state["tmp_files"])
        raise Canceled() from None
    except Exception as e:  # noqa: BLE001
        if is_canceled():
            _cleanup(state["tmp_files"])
            raise Canceled() from None
        raise friendly_error(e) from e

    if not info:
        raise FriendlyError("O yt-dlp não retornou informações do vídeo.")
    reqs = info.get("requested_downloads") or []
    path = Path(reqs[0]["filepath"]) if reqs and reqs[0].get("filepath") else None
    if not path or not path.exists():
        raise FriendlyError("Download terminou mas o arquivo não foi encontrado.", str(path))
    return path


def _cleanup(files: set[str]) -> None:
    """Remove arquivos parciais (.part, .ytdl, fragmentos) de um download cancelado."""
    time.sleep(0.2)  # yt-dlp pode estar fechando o arquivo
    for f in files:
        for p in (Path(f), Path(f + ".ytdl"), Path(str(Path(f).with_suffix("")) + ".part")):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                log.warning("não consegui remover %s", p)
        base = Path(f)
        for frag in base.parent.glob(f"{glob.escape(base.name)}-Frag*"):
            frag.unlink(missing_ok=True)


def info_fields(info: dict) -> dict:
    return {
        "title": (info.get("title") or "")[:300],
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration_s": info.get("duration"),
        "thumbnail_url": _thumb(info),
    }
