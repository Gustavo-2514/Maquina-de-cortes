"""Detecção de hardware e dependências externas (seção 8.8 / diagnóstico da seção 3)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx


@dataclass
class CheckItem:
    key: str
    label: str
    ok: bool
    detail: str = ""
    fix: str = ""  # instrução de correção (PT-BR) quando ok=False
    optional: bool = False


@dataclass
class Hardware:
    cuda: bool = False
    gpu_name: str | None = None
    vram_mb: int | None = None
    nvenc: bool = False
    extras: dict = field(default_factory=dict)


def _run(cmd: list[str], timeout: float = 10) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def nvidia_gpu() -> tuple[str | None, int | None]:
    if not shutil.which("nvidia-smi"):
        return None, None
    r = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not r or r.returncode != 0 or not r.stdout.strip():
        return None, None
    name, _, mem = r.stdout.strip().splitlines()[0].rpartition(",")
    try:
        return name.strip(), int(mem.strip())
    except ValueError:
        return name.strip(), None


def cuda_available() -> tuple[bool, str]:
    """CUDA utilizável pelo faster-whisper: dispositivo visível ao ctranslate2 + cuBLAS 12 e cuDNN 9 carregáveis."""
    try:
        import ctranslate2  # type: ignore[import-not-found]
    except ImportError:
        return False, "ctranslate2 não instalado (vem com faster-whisper)"
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception as e:  # noqa: BLE001
        return False, f"erro ao consultar CUDA: {e}"
    if n == 0:
        return False, "nenhum dispositivo CUDA visível"
    import ctypes

    missing = []
    for lib in ("libcublas.so.12", "libcudnn.so.9"):
        try:
            ctypes.CDLL(lib)
        except OSError:
            missing.append(lib)
    if missing:
        return False, f"{n} GPU(s), mas faltam: {', '.join(missing)} (inicie pelo run.py, que ajusta LD_LIBRARY_PATH)"
    return True, f"{n} dispositivo(s) CUDA, cuBLAS e cuDNN OK"


def ffmpeg_encoders() -> str:
    r = _run(["ffmpeg", "-hide_banner", "-encoders"])
    return r.stdout if r and r.returncode == 0 else ""


def ffmpeg_has_libass() -> bool:
    r = _run(["ffmpeg", "-hide_banner", "-filters"])
    if not r or r.returncode != 0:
        return False
    return any(line.split()[1:2] == ["ass"] for line in r.stdout.splitlines() if line.strip())


@lru_cache
def nvenc_works() -> bool:
    """Encoder listado não basta: testa encode real de 1 frame."""
    if "h264_nvenc" not in ffmpeg_encoders():
        return False
    r = _run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
            "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-",
        ],
        timeout=20,
    )
    return bool(r and r.returncode == 0)


def detect_hardware() -> Hardware:
    gpu, vram = nvidia_gpu()
    cuda, _ = cuda_available()
    return Hardware(cuda=cuda, gpu_name=gpu, vram_mb=vram, nvenc=nvenc_works() if shutil.which("ffmpeg") else False)


def recommended_defaults(hw: Hardware) -> dict:
    """Defaults de modelo/encoder a partir do hardware (sobrescrevíveis em Configurações)."""
    if hw.cuda and (hw.vram_mb or 0) >= 6000:
        whisper = {"model": "large-v3", "device": "cuda", "compute_type": "float16"}
    elif hw.cuda:
        whisper = {"model": "medium", "device": "cuda", "compute_type": "int8_float16"}
    else:
        whisper = {"model": "small", "device": "cpu", "compute_type": "int8"}
    llm = "qwen2.5:7b" if (hw.vram_mb or 0) >= 8000 else "qwen2.5:3b"
    return {"whisper": whisper, "encoder": "nvenc" if hw.nvenc else "x264", "ollama_model": llm}


def ollama_status(url: str, model: str) -> tuple[bool, bool, list[str], str]:
    """(online, modelo_presente, modelos, detalhe)"""
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return False, False, [], str(e) or type(e).__name__
    names = [m.get("name", "") for m in r.json().get("models", [])]
    want = model if ":" in model else f"{model}:latest"
    return True, want in names, names, f"{len(names)} modelo(s) instalado(s)"


def run_checks(data_dir: Path, ollama_url: str, ollama_model: str) -> dict:
    items: list[CheckItem] = []

    py_ok = sys.version_info >= (3, 11)
    items.append(CheckItem("python", "Python 3.11+", py_ok, sys.version.split()[0],
                           "Instale Python 3.11 ou mais novo."))

    has_ffmpeg = shutil.which("ffmpeg") is not None
    items.append(CheckItem("ffmpeg", "FFmpeg", has_ffmpeg, shutil.which("ffmpeg") or "não encontrado no PATH",
                           "Ubuntu: sudo apt install ffmpeg"))
    has_ffprobe = shutil.which("ffprobe") is not None
    items.append(CheckItem("ffprobe", "FFprobe", has_ffprobe, shutil.which("ffprobe") or "não encontrado no PATH",
                           "Vem junto com o ffmpeg: sudo apt install ffmpeg"))
    libass = has_ffmpeg and ffmpeg_has_libass()
    items.append(CheckItem("libass", "FFmpeg com libass (legendas)", libass,
                           "filtro 'ass' disponível" if libass else "filtro 'ass' ausente",
                           "Use um build do ffmpeg com --enable-libass (o do apt já tem)."))

    online, has_model, models, detail = ollama_status(ollama_url, ollama_model)
    items.append(CheckItem("ollama", "Ollama rodando", online, f"{ollama_url} — {detail}",
                           "Instale: curl -fsSL https://ollama.com/install.sh | sh  e rode: ollama serve"))
    items.append(CheckItem("ollama_model", f"Modelo LLM ({ollama_model})", has_model,
                           ", ".join(models) if models else "nenhum modelo",
                           f"ollama pull {ollama_model}"))

    gpu, vram = nvidia_gpu()
    items.append(CheckItem("gpu", "GPU NVIDIA", gpu is not None,
                           f"{gpu} — {vram} MB" if gpu else "não detectada (funciona em CPU, só mais lento)",
                           "Opcional. Instale o driver NVIDIA para acelerar.", optional=True))
    cuda, cuda_detail = cuda_available()
    items.append(CheckItem("cuda", "CUDA (faster-whisper)", cuda, cuda_detail,
                           "Opcional. Requer driver NVIDIA + libs CUDA 12/cuDNN 9 (pip: nvidia-cublas-cu12 nvidia-cudnn-cu12).",
                           optional=True))
    nvenc = has_ffmpeg and nvenc_works()
    items.append(CheckItem("nvenc", "NVENC (encode por GPU)", nvenc,
                           "h264_nvenc funcional" if nvenc else "indisponível — usará libx264",
                           "Opcional. Requer GPU NVIDIA e ffmpeg com suporte a nvenc.", optional=True))

    usage = shutil.disk_usage(data_dir)
    free_gb = usage.free / 1024**3
    items.append(CheckItem("disk", "Espaço em disco", free_gb >= 10, f"{free_gb:.1f} GB livres em {data_dir}",
                           "Libere espaço: recomendado pelo menos 10 GB."))

    hw = Hardware(cuda=cuda, gpu_name=gpu, vram_mb=vram, nvenc=nvenc)
    return {
        "ok": all(i.ok for i in items if not i.optional),
        "items": [asdict(i) for i in items],
        "hardware": asdict(hw),
        "recommended": recommended_defaults(hw),
    }
