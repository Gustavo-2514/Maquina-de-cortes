"""Tradução de exceções para mensagens em PT-BR (o detalhe técnico vai junto, expansível na UI)."""

from __future__ import annotations

import errno
import traceback

# exceções que já nascem com mensagem amigável em PT-BR (têm `.detail`)
_FRIENDLY_TYPES = ("FriendlyError", "ProbeError", "HighlightError", "FFmpegError", "ReframeError", "ProjectError")

_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("cuda out of memory", "out of memory", "cublas_status_alloc_failed", "cudaerrormemoryallocation"),
     "A placa de vídeo ficou sem memória. Feche outros programas que usam a GPU ou escolha um modelo menor "
     "do Whisper em Configurações."),
    (("libcublas", "libcudnn", "cudnn", "cuda driver", "no cuda-capable device", "cuda failed"),
     "Problema com a GPU/CUDA. Inicie o app pelo scripts/start.sh ou mude o dispositivo para CPU em Configurações."),
    (("no space left on device",), "O disco está cheio. Libere espaço (Configurações → Armazenamento) e tente de novo."),
    (("ollama",), "Falha ao falar com o Ollama. Confira em Configurações → Testar."),
    (("connection refused", "connecterror", "timed out", "timeout"),
     "Um serviço local não respondeu a tempo. Tente de novo; se persistir, reinicie o app."),
]


def friendly(exc: BaseException) -> tuple[str, str]:
    """(mensagem para o usuário, detalhe técnico)."""
    detail = getattr(exc, "detail", "") or ""
    if type(exc).__name__ in _FRIENDLY_TYPES and str(exc):
        return str(exc), detail or traceback.format_exc()
    tb = "".join(traceback.format_exception(exc))
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return _PATTERNS[2][1], tb
        if isinstance(exc, PermissionError):
            return f"Sem permissão para acessar um arquivo: {exc.filename or ''}".strip(), tb
        if isinstance(exc, FileNotFoundError):
            return f"Arquivo não encontrado: {exc.filename or ''}".strip(), tb
    low = f"{type(exc).__name__}: {exc}".lower()
    for needles, msg in _PATTERNS:
        if any(n in low for n in needles):
            return msg, tb
    msg = str(exc).strip()
    # mensagens nossas (RuntimeError("…")) já estão em PT-BR
    if msg and isinstance(exc, RuntimeError) and type(exc) is RuntimeError:
        return msg, tb
    return f"Erro inesperado ({type(exc).__name__}). Veja o detalhe técnico.", tb
