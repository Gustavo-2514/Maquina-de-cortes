"""Baixa os modelos de IA e mostra o diagnóstico (usado pelo scripts/setup.sh via run.py).

python -m app.prefetch            → baixa Whisper (pelo hardware) e o modelo do Ollama
python -m app.prefetch --check    → só o diagnóstico, em texto
"""

from __future__ import annotations

import json
import sys

import httpx

from .config import get_settings, load_user_settings, save_user_settings
from .services import hardware


def check() -> int:
    us = load_user_settings()
    res = hardware.run_checks(get_settings().data_dir, us.ollama_url, us.ollama_model)
    for it in res["items"]:
        mark = "✓" if it["ok"] else ("!" if it["optional"] else "✗")
        print(f"  {mark} {it['label']}: {it['detail']}")
        if not it["ok"] and it["fix"]:
            print(f"      → {it['fix']}")
    print("\n  Tudo pronto!" if res["ok"] else "\n  Há pendências (✗) — veja as instruções acima.")
    return 0 if res["ok"] else 1


def pull_ollama(url: str, model: str) -> bool:
    print(f"→ Baixando o modelo de IA {model} no Ollama (alguns GB, só na primeira vez)…", flush=True)
    last = ""
    try:
        with httpx.stream("POST", f"{url.rstrip('/')}/api/pull", json={"model": model, "stream": True},
                          timeout=httpx.Timeout(10, read=None)) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("error"):
                    print(f"  ✗ {msg['error']}")
                    return False
                status = msg.get("status", "")
                if msg.get("total") and msg.get("completed"):
                    status = f"{status} {100 * msg['completed'] / msg['total']:.0f}%"
                if status != last:
                    print(f"\r  {status:<60}", end="", flush=True)
                    last = status
        print()
        return True
    except httpx.HTTPError as e:
        print(f"\n  ✗ Ollama não respondeu: {e}")
        return False


def prefetch() -> int:
    us = load_user_settings()
    hw = hardware.detect_hardware()
    rec = hardware.recommended_defaults(hw)
    gpu = f"{hw.gpu_name} ({(hw.vram_mb or 0) // 1024} GB)" if hw.gpu_name else "nenhuma (vai usar a CPU)"
    print(f"  GPU: {gpu} · CUDA utilizável: {'sim' if hw.cuda else 'não'} · NVENC: {'sim' if hw.nvenc else 'não'}")

    from .services.transcriber import resolve_config

    model, device, _ = resolve_config(us)
    print(f"→ Baixando o Whisper {model} ({'GPU' if device == 'cuda' else 'CPU'})…", flush=True)
    from faster_whisper.utils import download_model

    download_model(model)
    print("  ✓ Whisper pronto")

    ok = True
    try:
        names = [m["name"] for m in httpx.get(f"{us.ollama_url.rstrip('/')}/api/tags", timeout=5).json().get("models", [])]
    except httpx.HTTPError:
        print("  ! Ollama não está rodando — pulei o modelo de IA. Depois rode: ollama pull " + rec["ollama_model"])
        return 1
    want = us.ollama_model
    # padrão de fábrica (7b) numa máquina sem GPU de 8 GB → usa o recomendado (3b)
    if want == "qwen2.5:7b" and rec["ollama_model"] != want and want not in names:
        want = rec["ollama_model"]
        us.ollama_model = want
        save_user_settings(us)
    if want in names or f"{want}:latest" in names:
        print(f"  ✓ Modelo de IA {want} já instalado")
    else:
        ok = pull_ollama(us.ollama_url, want)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else prefetch())
