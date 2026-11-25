#!/usr/bin/env python3
"""Sugere os modelos de IA locais (Whisper e Ollama) que cabem no seu computador.

Olha a placa de vídeo, a memória RAM, o processador e o disco, e diz qual modelo de
transcrição (Whisper) e qual modelo de IA (Ollama) usar — e por quê.

Uso:
    scripts/sugerir-modelos.sh               (Linux/macOS)
    scripts\\sugerir-modelos.bat              (Windows)
    python3 scripts/sugerir_modelos.py [opções]

Opções:
    --aplicar   salva a sugestão nas Configurações do app (data/settings.json)
                e oferece baixar o modelo de IA no Ollama
    --sim       com --aplicar: não pergunta nada, já baixa
    --json      saída em JSON (para outros programas)

Só usa a biblioteca padrão do Python (3.8+): funciona antes mesmo da instalação.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "data" / "settings.json"
OLLAMA_URL = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")

# Tamanho do download (GB). Ollama: quantização padrão (Q4_K_M). Whisper: formato do faster-whisper.
OLLAMA_SIZES = {"qwen2.5:1.5b": 1.0, "qwen2.5:3b": 1.9, "qwen2.5:7b": 4.7, "qwen2.5:14b": 9.0, "qwen2.5:32b": 20.0}
WHISPER_SIZES = {"tiny": 0.08, "base": 0.15, "small": 0.5, "medium": 1.5, "turbo": 1.6, "large-v3": 3.1}

GB = 1024**3


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------
def _run(cmd: list[str], timeout: float = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def ram_gb() -> float | None:
    system = platform.system()
    try:
        if system == "Linux":
            m = re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text())
            return int(m.group(1)) * 1024 / GB if m else None
        if system == "Darwin":
            out = _run(["sysctl", "-n", "hw.memsize"]).strip()
            return int(out) / GB if out else None
        if system == "Windows":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return st.ullTotalPhys / GB
    except (OSError, ValueError, AttributeError):
        pass
    return None


def cpu_name() -> str:
    system = platform.system()
    if system == "Linux":
        try:
            m = re.search(r"model name\s*:\s*(.+)", Path("/proc/cpuinfo").read_text())
            if m:
                return m.group(1).strip()
        except OSError:
            pass
    if system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if name:
            return name
    return platform.processor() or platform.machine() or "desconhecido"


def nvidia_gpu() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out.strip():
        return None  # nvidia-smi existe, mas o driver não respondeu
    name, _, mem = out.strip().splitlines()[0].rpartition(",")
    try:
        return {"vendor": "nvidia", "name": name.strip(), "vram_gb": int(mem.strip()) / 1024}
    except ValueError:
        return {"vendor": "nvidia", "name": name.strip(), "vram_gb": None}


def amd_gpu() -> dict | None:
    """Só Linux: placas AMD dedicadas expõem a VRAM em /sys (driver amdgpu)."""
    if platform.system() != "Linux":
        return None
    best = None
    for card in Path("/sys/class/drm").glob("card[0-9]*"):
        dev = card / "device"
        try:
            if (dev / "vendor").read_text().strip() != "0x1002":
                continue
            vram = int((dev / "mem_info_vram_total").read_text()) / GB
        except (OSError, ValueError):
            continue
        if vram >= 2 and (best is None or vram > best["vram_gb"]):  # < 2 GB = gráfico integrado
            best = {"vendor": "amd", "name": "Placa AMD Radeon", "vram_gb": vram}
    return best


def apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def disk_free_gb() -> float:
    target = ROOT / "data" if (ROOT / "data").exists() else ROOT
    return shutil.disk_usage(target).free / GB


def ollama_models() -> list[str] | None:
    """Modelos instalados no Ollama; None = Ollama não está rodando."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            return [m.get("name", "") for m in json.load(r).get("models", [])]
    except (OSError, ValueError):
        return None


def detect() -> dict:
    gpu = nvidia_gpu() or amd_gpu()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu_name(),
        "cores": os.cpu_count() or 1,
        "ram_gb": ram_gb(),
        "gpu": gpu,
        "apple_silicon": apple_silicon(),
        "disk_free_gb": disk_free_gb(),
        "ollama_installed": shutil.which("ollama") is not None
        or (Path.home() / ".local" / "bin" / "ollama").exists(),
        "ollama_models": ollama_models(),
    }


# ---------------------------------------------------------------------------
# Regras de sugestão
# ---------------------------------------------------------------------------
def suggest(hw: dict) -> dict:
    gpu = hw["gpu"] or {}
    nvidia = gpu.get("vendor") == "nvidia"
    vram = gpu.get("vram_gb") or 0
    ram = hw["ram_gb"] or 0
    cores = hw["cores"]
    notes: list[str] = []

    # ---- Whisper (transcrição). Só usa GPU NVIDIA (CUDA); o resto vai para a CPU.
    if nvidia and vram >= 5.5:
        whisper = {"model": "large-v3", "device": "cuda", "compute_type": "float16",
                   "why": "a melhor precisão; cabe na sua placa e transcreve 1 hora de vídeo em poucos minutos",
                   "alt": "turbo — quase a mesma qualidade e ~2× mais rápido"}
    elif nvidia and vram >= 3.5:
        whisper = {"model": "medium", "device": "cuda", "compute_type": "int8_float16",
                   "why": "o maior que cabe com folga na sua placa (int8 economiza memória)",
                   "alt": "turbo (int8_float16) — mais rápido, qualidade parecida"}
    elif nvidia:
        whisper = {"model": "small", "device": "cuda", "compute_type": "int8_float16",
                   "why": "placa com pouca memória: o small é o que cabe sem travar",
                   "alt": "base — se aparecer erro de memória da placa de vídeo"}
    elif cores >= 8 and ram >= 13:
        whisper = {"model": "small", "device": "cpu", "compute_type": "int8",
                   "why": "sem placa NVIDIA a transcrição roda no processador; o small é o melhor equilíbrio",
                   "alt": "medium — mais preciso, mas ~3× mais lento na CPU"}
    else:
        whisper = {"model": "base", "device": "cpu", "compute_type": "int8",
                   "why": "computador mais modesto: o base transcreve rápido o bastante na CPU",
                   "alt": "small — mais preciso, se você não se importar de esperar mais"}

    # ---- Ollama (IA que escolhe os cortes). Ollama usa NVIDIA, AMD (Linux/Windows) e Apple Silicon.
    # Na NVIDIA com menos de 10 GB o app tira o Whisper da memória antes da IA, então a placa toda fica livre.
    if hw["apple_silicon"]:
        mem, where = ram * 0.65, "memória unificada do Mac"
    elif gpu and vram:
        mem, where = vram, f"placa de vídeo ({'NVIDIA' if nvidia else 'AMD'})"
    else:
        mem, where = 0, "processador"

    if mem >= 14:
        llm = {"model": "qwen2.5:14b", "why": f"cabe inteiro na {where}: escolhe cortes melhores que o 7b",
               "alt": "qwen2.5:7b — o modelo mais testado com o app, mais rápido"}
        if mem >= 30:
            llm["alt"] = "qwen2.5:32b — ainda melhor, se você não usar a placa para mais nada ao mesmo tempo"
    elif mem >= 7.5:
        llm = {"model": "qwen2.5:7b", "why": f"cabe inteiro na {where}; é o modelo padrão e o mais testado com o app",
               "alt": "qwen2.5:3b — se a análise ficar lenta ou faltar memória"}
    elif mem >= 5.5:
        llm = {"model": "qwen2.5:3b", "why": f"cabe inteiro na {where} e responde rápido",
               "alt": "qwen2.5:7b — escolhe cortes melhores; cabe quase todo, fica um pouco mais lento"}
    elif mem >= 2:
        llm = {"model": "qwen2.5:3b", "why": f"parte roda na {where} e parte no processador",
               "alt": "qwen2.5:1.5b — mais rápido, mas escolhe cortes piores"}
    elif ram >= 13 and cores >= 8:
        llm = {"model": "qwen2.5:3b", "why": "sem placa de vídeo compatível a IA roda no processador; o 3b é rápido o bastante",
               "alt": "qwen2.5:7b — escolhe cortes melhores, mas a análise leva bem mais tempo"}
    elif ram >= 6.5:
        llm = {"model": "qwen2.5:3b", "why": "roda no processador; é o menor modelo que ainda escolhe bons cortes",
               "alt": "qwen2.5:1.5b — se o computador ficar travando durante a análise"}
    else:
        llm = {"model": "qwen2.5:1.5b", "why": "pouca memória RAM: só os modelos bem pequenos rodam",
               "alt": "IA paga por chave de API (OpenRouter, Claude…) — veja o README"}
        notes.append("Com menos de 8 GB de RAM a IA local fica fraca. Vale considerar a IA paga "
                     "(Configurações → IA paga), que custa centavos por vídeo.")

    if not gpu and not hw["apple_silicon"]:
        notes.append("Sem placa de vídeo compatível tudo roda no processador: funciona, só demora mais. "
                     "Um vídeo de 1 hora pode levar de 30 minutos a algumas horas para analisar.")
    if gpu.get("vendor") == "amd":
        notes.append("Placas AMD aceleram a IA do Ollama (se a sua for compatível com ROCm), "
                     "mas a transcrição (Whisper) usa só o processador.")
    if hw["apple_silicon"]:
        notes.append("No Mac com chip Apple a IA do Ollama usa a GPU do chip; a transcrição usa o processador.")
    if not nvidia:
        notes.append("Sem NVIDIA a codificação do vídeo final usa o processador (x264): qualidade igual, só mais lenta.")

    need = OLLAMA_SIZES.get(llm["model"], 5) + WHISPER_SIZES.get(whisper["model"], 1) + 10
    if hw["disk_free_gb"] < need:
        notes.append(f"Pouco espaço em disco: {hw['disk_free_gb']:.0f} GB livres. "
                     f"Recomendado pelo menos {need:.0f} GB (modelos + vídeos).")

    encoder = "nvenc" if nvidia else "x264"
    return {"whisper": whisper, "llm": llm, "encoder": encoder, "notes": notes}


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
def _c(code: str) -> str:
    return f"\033[{code}m" if sys.stdout.isatty() and os.name != "nt" else ""


B, G, Y, D, N = _c("1"), _c("32"), _c("33"), _c("2"), _c("0")


def show(hw: dict, s: dict) -> None:
    gpu = hw["gpu"]
    print(f"\n{B}Seu computador{N}")
    print(f"  Sistema       {hw['os']}")
    print(f"  Processador   {hw['cpu']} ({hw['cores']} núcleos)")
    print(f"  Memória RAM   {hw['ram_gb']:.0f} GB" if hw["ram_gb"] else "  Memória RAM   não consegui ler")
    if gpu:
        vram = f"{gpu['vram_gb']:.0f} GB" if gpu.get("vram_gb") else "memória desconhecida"
        print(f"  Placa vídeo   {gpu['name']} — {vram}")
    elif hw["apple_silicon"]:
        print("  Placa vídeo   GPU do chip Apple (usa a memória RAM)")
    else:
        print(f"  Placa vídeo   {Y}nenhuma compatível encontrada{N} (tudo vai rodar no processador)")
    print(f"  Disco livre   {hw['disk_free_gb']:.0f} GB")

    w, llm = s["whisper"], s["llm"]
    print(f"\n{B}Sugestão{N}")
    print(f"  {G}Transcrição (Whisper):{N} {B}{w['model']}{N}  "
          f"{D}[{'placa de vídeo' if w['device'] == 'cuda' else 'processador'} · {w['compute_type']} · "
          f"~{WHISPER_SIZES[w['model']]:.1f} GB]{N}")
    print(f"     Por quê: {w['why']}.")
    print(f"     Alternativa: {w['alt']}.")
    print(f"  {G}IA que escolhe os cortes (Ollama):{N} {B}{llm['model']}{N}  "
          f"{D}[~{OLLAMA_SIZES[llm['model']]:.1f} GB]{N}")
    print(f"     Por quê: {llm['why']}.")
    print(f"     Alternativa: {llm['alt']}.")
    print(f"  {G}Codificação do vídeo:{N} {s['encoder']} {D}(o app escolhe sozinho){N}")

    if s["notes"]:
        print(f"\n{B}Bom saber{N}")
        for n in s["notes"]:
            print(f"  • {n}")

    models = hw["ollama_models"]
    print(f"\n{B}Próximos passos{N}")
    if models is not None and (llm["model"] in models or f"{llm['model']}:latest" in models):
        print(f"  ✓ O modelo {llm['model']} já está instalado no Ollama.")
    elif hw["ollama_installed"]:
        print(f"  • Baixar o modelo de IA:   ollama pull {llm['model']}")
    else:
        print("  • O Ollama ainda não está instalado: rode primeiro  scripts/setup.sh")
    print(f"  • Usar estes modelos no app: rode este script com {B}--aplicar{N}")
    print("    (ou escolha em Configurações → Preferências, com o app aberto)")
    print()


def apply(hw: dict, s: dict, assume_yes: bool) -> int:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if SETTINGS.exists():
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    w = s["whisper"]
    data.update({"whisper_model": w["model"], "whisper_device": w["device"],
                 "whisper_compute_type": w["compute_type"], "ollama_model": s["llm"]["model"]})
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS)
    print(f"{G}✓{N} Configurações salvas em data/settings.json "
          f"(Whisper {w['model']} · {s['llm']['model']}).")
    print("  Para voltar ao automático: Configurações → Preferências → Modelo: Automático.")

    model = s["llm"]["model"]
    installed = hw["ollama_models"]
    if installed is not None and (model in installed or f"{model}:latest" in installed):
        return 0
    exe = shutil.which("ollama") or str(Path.home() / ".local" / "bin" / "ollama")
    if not Path(exe).exists():
        print(f"{Y}!{N} Ollama não encontrado. Depois de rodar scripts/setup.sh:  ollama pull {model}")
        return 0
    if installed is None:
        print(f"{Y}!{N} O Ollama não está rodando. Abra o app (scripts/start.sh) e depois rode:  ollama pull {model}")
        return 0
    if not assume_yes:
        ans = input(f"Baixar {model} agora (~{OLLAMA_SIZES.get(model, 5):.1f} GB)? [S/n] ").strip().lower()
        if ans not in ("", "s", "sim", "y", "yes"):
            print(f"  Tudo bem. Quando quiser:  ollama pull {model}")
            return 0
    return subprocess.call([exe, "pull", model])


def main() -> int:
    ap = argparse.ArgumentParser(description="Sugere os modelos de IA locais pelo seu hardware.")
    ap.add_argument("--aplicar", action="store_true", help="salva a sugestão nas Configurações do app")
    ap.add_argument("--sim", action="store_true", help="não pergunta antes de baixar o modelo")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    args = ap.parse_args()

    hw = detect()
    s = suggest(hw)
    if args.json:
        print(json.dumps({"hardware": hw, "sugestao": s}, indent=2, ensure_ascii=False))
        return 0
    show(hw, s)
    return apply(hw, s, args.sim) if args.aplicar else 0


if __name__ == "__main__":
    sys.exit(main())
