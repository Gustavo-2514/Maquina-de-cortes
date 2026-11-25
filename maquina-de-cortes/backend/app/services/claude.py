"""Claude (Anthropic API) como provedor OPCIONAL de IA — o padrão continua sendo o Ollama local.

Os outros provedores pagos (OpenAI, Gemini, OpenRouter…) ficam em `openai_compat.py`; `ai.py` escolhe entre eles.

Tudo aqui gasta dinheiro de verdade, então o módulo também:
- estima o custo ANTES (`estimate_analysis`, `estimate_review`) para a UI mostrar e o usuário confirmar;
- registra o custo REAL de cada chamada (`CostMeter`, a partir de `response.usage`).

Preços de tabela da API (US$ por milhão de tokens), conferidos em 2026-11-03. Mudam com o tempo:
o valor exibido é uma estimativa, a fatura da Anthropic é a fonte da verdade.
"""

from __future__ import annotations

import copy
import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .highlighter import Canceled, HighlightError, LLMCall

log = logging.getLogger(__name__)

PRICES_AS_OF = "2026-11-03"
# model id → (entrada, saída) em US$/1M tokens
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),  # até 100 mil tokens de entrada por pedido (nossos pedidos ficam bem abaixo)
}
MODEL_LABELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (melhor qualidade)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (equilíbrio)",
    "claude-haiku-5-5": "Claude Haiku 5.5 (mais barato)",
}
DEFAULT_MODEL = "claude-opus-5-5"
# fallback no servidor quando o modelo recusa o pedido (não existe para o Haiku 5.5)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}

# Heurísticas de tamanho (medidas nos projetos locais: ~19–23 caracteres de prompt por segundo de vídeo
# em gameplay; fala contínua/podcast chega a ~30). Português ≈ 3 caracteres por token — arredondado para cima.
CHARS_PER_TOKEN = 3.0
PROMPT_CHARS_PER_VIDEO_S = 30.0
THINKING_TOKENS_PER_CALL = 2500  # esforço "medium": raciocínio é cobrado como saída
OUTPUT_TOKENS_PER_CLIP = 160
IMAGE_TOKENS = 450  # quadro 9:16 reduzido para 405×720 px (≈ largura×altura/750 = 389, arredondado para cima)


def price_of(model: str) -> tuple[float, float]:
    return PRICES.get(model, PRICES[DEFAULT_MODEL])


def usd(model: str, input_tokens: float, output_tokens: float) -> float:
    pin, pout = price_of(model)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


# ---------------------------------------------------------------------------
# Estimativas (antes de rodar)
# ---------------------------------------------------------------------------
Prices = tuple[float | None, float | None]


def _usd_or_none(model: str, prices: Prices | None, input_tokens: float, output_tokens: float) -> float | None:
    if prices is None:
        return usd(model, input_tokens, output_tokens)
    pin, pout = prices
    if pin is None or pout is None:
        return None
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


def estimate_analysis(model: str, n_windows: int, per_window: int, prompt_chars: float,
                      prices: Prices | None = None, prices_as_of: str | None = None) -> dict:
    """Custo estimado da análise: uma chamada por janela de transcrição.

    `prices` = (entrada, saída) US$/1M de outro provedor; None = tabela do Claude. Preço desconhecido → usd None.
    `max_usd` cobre o pior caso (cada janela repetida 1× por JSON inválido)."""
    input_tokens = prompt_chars / CHARS_PER_TOKEN
    output_tokens = n_windows * (THINKING_TOKENS_PER_CALL + per_window * OUTPUT_TOKENS_PER_CLIP)
    cost = _usd_or_none(model, prices, input_tokens, output_tokens)
    return {"model": model, "calls": n_windows, "input_tokens": round(input_tokens),
            "output_tokens": round(output_tokens), "usd": None if cost is None else round(cost, 4),
            "max_usd": None if cost is None else round(cost * 2, 4),
            "prices_as_of": prices_as_of or PRICES_AS_OF}


def estimate_review(model: str, n_frames: int, transcript_chars: int,
                    prices: Prices | None = None, prices_as_of: str | None = None) -> dict:
    """Custo estimado da revisão visual de UM corte (n quadros + transcrição do corte)."""
    input_tokens = n_frames * IMAGE_TOKENS + transcript_chars / CHARS_PER_TOKEN + 900  # 900 = instruções
    output_tokens = THINKING_TOKENS_PER_CALL + 600
    cost = _usd_or_none(model, prices, input_tokens, output_tokens)
    return {"model": model, "calls": 1, "input_tokens": round(input_tokens), "output_tokens": output_tokens,
            "usd": None if cost is None else round(cost, 4), "prices_as_of": prices_as_of or PRICES_AS_OF}


# ---------------------------------------------------------------------------
# Custo real (depois de rodar)
# ---------------------------------------------------------------------------
@dataclass
class CostMeter:
    """Custo real somado das chamadas de um job. Serve a qualquer provedor (`provider` vai para o registro)."""

    provider: str = "claude"
    prices_as_of: str = PRICES_AS_OF
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    priced: bool = True  # False se alguma chamada não teve preço conhecido (o usd fica subestimado)
    approx: bool = False  # True se o provedor não informou o uso e os tokens foram estimados pelo texto
    models: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage) -> None:  # noqa: ANN001  (BetaUsage do SDK da Anthropic)
        # cache_* não são usados aqui, mas entram na conta se aparecerem
        inp = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out = usage.output_tokens or 0
        self.add_tokens(model, inp, out, usd(model, inp, out))

    def add_tokens(self, model: str, inp: int, out: int, cost: float | None, approx: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += inp
            self.output_tokens += out
            if cost is None:
                self.priced = False
            else:
                self.usd += cost
            self.approx = self.approx or approx
            self.models.add(model)

    def as_dict(self) -> dict:
        d = {"provider": self.provider, "models": sorted(self.models), "calls": self.calls,
             "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
             "usd": round(self.usd, 4), "prices_as_of": self.prices_as_of}
        if not self.priced:
            d["priced"] = False
        if self.approx:
            d["approx"] = True
        return d


# ---------------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------------
def strict_schema(schema: dict) -> dict:
    """Structured outputs exige `additionalProperties: false` em todo objeto e não aceita limites numéricos
    (`minimum`/`maximum`) — o parse local já faz o clamp das notas."""
    s = copy.deepcopy(schema)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            node.pop("minimum", None)
            node.pop("maximum", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node.setdefault("required", list(node.get("properties", {})))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


def make_client(api_key: str):  # noqa: ANN201
    import anthropic

    # chave das Configurações; vazia = variável ANTHROPIC_API_KEY / perfil do `ant auth login`
    return anthropic.Anthropic(api_key=api_key or None, timeout=300.0, max_retries=2)


def _friendly(e: Exception) -> HighlightError:
    import anthropic

    if isinstance(e, anthropic.AuthenticationError):
        return HighlightError("A chave da API da Anthropic é inválida.", "Confira em Configurações → Claude.")
    if isinstance(e, anthropic.PermissionDeniedError):
        return HighlightError("A chave da Anthropic não tem permissão para este modelo.", str(e))
    if isinstance(e, anthropic.RateLimitError):
        return HighlightError("Limite de uso da API da Anthropic atingido. Tente de novo em instantes.", str(e))
    if isinstance(e, anthropic.BadRequestError):
        msg = str(e)
        if "credit" in msg.lower() or "billing" in msg.lower():
            return HighlightError("Sem créditos na conta da Anthropic.", msg)
        return HighlightError("A API da Anthropic recusou o pedido.", msg)
    if isinstance(e, anthropic.APIConnectionError):
        return HighlightError("Sem conexão com a API da Anthropic.", str(e))
    if isinstance(e, anthropic.APIStatusError):
        return HighlightError(f"Erro na API da Anthropic ({e.status_code}).", str(e))
    return HighlightError("Erro ao chamar o Claude.", str(e))


def create(client, model: str, system: str, content: list[dict] | str, schema: dict, meter: CostMeter,  # noqa: ANN001
           is_canceled: Callable[[], bool] = lambda: False, on_chunk: Callable[[int], None] | None = None,
           effort: str = "medium", max_tokens: int = 16000) -> str:
    """Uma chamada com saída JSON garantida pelo schema. Streaming para poder cancelar no meio."""
    import anthropic

    kwargs: dict = {}
    if model in FALLBACK_MODELS:
        kwargs = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    parts: list[str] = []
    try:
        with client.beta.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            **kwargs,
        ) as stream:
            for text in stream.text_stream:
                if is_canceled():
                    raise Canceled()
                parts.append(text)
                if on_chunk:
                    on_chunk(len(parts))
            msg = stream.get_final_message()
    except Canceled:
        raise
    except anthropic.AnthropicError as e:
        raise _friendly(e) from e
    except TypeError as e:  # SDK sem nenhuma credencial (nem chave, nem ANTHROPIC_API_KEY, nem perfil)
        if "authentication" not in str(e).lower():
            raise
        raise HighlightError("Nenhuma chave da Anthropic configurada.",
                             "Informe a chave em Configurações → Claude ou defina ANTHROPIC_API_KEY.") from e
    meter.add(msg.model or model, msg.usage)
    log.info("claude %s: %s tokens entrada, %s saída (req %s)", msg.model, msg.usage.input_tokens,
             msg.usage.output_tokens, getattr(msg, "_request_id", "?"))
    if msg.stop_reason == "refusal":
        cat = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        raise HighlightError("O Claude recusou analisar este trecho.", f"categoria: {cat}")
    if msg.stop_reason == "max_tokens":
        raise HighlightError("A resposta do Claude foi cortada (limite de tokens).", "")
    return "".join(b.text for b in msg.content if b.type == "text") or "".join(parts)


def claude_chat(api_key: str, model: str, meter: CostMeter, is_canceled: Callable[[], bool],
                on_chunk: Callable[[int], None] | None = None, schema: dict | None = None) -> LLMCall:
    """Mesmo contrato do `ollama_chat`: (messages, temperature) → texto JSON.

    A temperatura é ignorada (os modelos atuais não aceitam o parâmetro)."""
    from .highlighter import SCHEMA

    client = make_client(api_key)

    def call(messages: list[dict], _temperature: float) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        return create(client, model, system, user, schema or SCHEMA, meter, is_canceled, on_chunk)

    return call


def windows_cost_inputs(duration: float, num_clips: int, factor: float, n_windows: int,
                        prompt_chars: float | None) -> tuple[int, float]:
    """(candidatos por janela, caracteres de prompt) — espelha `find_highlights`."""
    per_window = math.ceil(num_clips * factor / max(1, n_windows)) + 1
    chars = prompt_chars if prompt_chars is not None else duration * PROMPT_CHARS_PER_VIDEO_S
    return per_window, chars + n_windows * 1800  # 1800 ≈ instruções do sistema + template por chamada
