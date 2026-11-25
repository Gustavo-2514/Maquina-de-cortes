"""IA paga por chave de API: registro de provedores e roteamento das chamadas.

Uma "ref" de modelo identifica provedor + modelo:
- ids do Claude sem prefixo (`claude-opus-5-5`) — formato antigo, continua valendo;
- `<provedor>:<id do modelo>` para os demais (`openai:gpt-…`, `openrouter:anthropic/claude-…`, `gemini:gemini-…`).

O Claude usa o SDK da Anthropic (`claude.py`); os outros, o cliente compatível com OpenAI (`openai_compat.py`).
O Ollama local (grátis) continua fora daqui: `llm == "ollama"`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass

from . import claude, openai_compat
from .highlighter import LLMCall


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str  # vazio = vem das Configurações (custom) ou não se aplica (anthropic)
    env: str
    key_hint: str
    keys_url: str
    vision_default: bool = True


PROVIDERS: dict[str, Provider] = {p.key: p for p in [
    Provider("anthropic", "Anthropic (Claude)", "", "ANTHROPIC_API_KEY", "sk-ant-…",
             "https://console.anthropic.com/settings/keys"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "sk-or-…",
             "https://openrouter.ai/settings/keys"),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", "sk-…",
             "https://platform.openai.com/api-keys"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
             "AIza…", "https://aistudio.google.com/apikey"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "sk-…",
             "https://platform.deepseek.com/api_keys", vision_default=False),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1", "XAI_API_KEY", "xai-…", "https://console.x.ai"),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "gsk_…",
             "https://console.groq.com/keys", vision_default=False),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "",
             "https://console.mistral.ai/api-keys", vision_default=False),
    Provider("custom", "Outro (compatível com OpenAI)", "", "CUSTOM_LLM_API_KEY", "", "", vision_default=False),
]}


@dataclass(frozen=True)
class ModelInfo:
    ref: str
    provider: str
    id: str
    label: str
    input_per_mtok: float | None
    output_per_mtok: float | None
    vision: bool
    prices_as_of: str

    @property
    def prices(self) -> tuple[float | None, float | None]:
        return (self.input_per_mtok, self.output_per_mtok)

    @property
    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None


def make_ref(provider: str, model_id: str) -> str:
    return model_id if provider == "anthropic" and model_id in claude.PRICES else f"{provider}:{model_id}"


def split_ref(ref: str) -> tuple[str, str]:
    if ref in claude.PRICES:
        return "anthropic", ref
    provider, sep, model_id = ref.partition(":")
    if not sep or provider not in PROVIDERS:
        return "", ref
    return provider, model_id


# ---------------------------------------------------------------------------
# Chaves e modelos disponíveis
# ---------------------------------------------------------------------------
def api_key(us, provider: str) -> str:  # noqa: ANN001  (UserSettings)
    if provider == "anthropic":
        return us.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    p = PROVIDERS.get(provider)
    return (us.api_keys.get(provider) or "").strip() or (os.environ.get(p.env, "") if p else "")


def base_url(us, provider: str) -> str:  # noqa: ANN001
    return us.custom_base_url.strip() if provider == "custom" else PROVIDERS[provider].base_url


def configured(us, provider: str) -> bool:  # noqa: ANN001
    if provider == "custom" and not us.custom_base_url.strip():
        return False
    # Claude: o SDK também acha o perfil do `ant auth login`, mas aqui só contamos chave explícita/variável
    return bool(api_key(us, provider))


def list_models(us) -> list[ModelInfo]:  # noqa: ANN001
    """Claude (tabela embutida) + modelos que o usuário adicionou nas Configurações."""
    out = [ModelInfo(m, "anthropic", m, claude.MODEL_LABELS[m], p[0], p[1], True, claude.PRICES_AS_OF)
           for m, p in claude.PRICES.items()]
    seen = {m.ref for m in out}
    for m in us.ai_models:
        if m.provider not in PROVIDERS or not m.id.strip():
            continue
        ref = make_ref(m.provider, m.id.strip())
        if ref in seen:
            continue
        seen.add(ref)
        label = m.label.strip() or m.id.strip()
        out.append(ModelInfo(ref, m.provider, m.id.strip(), f"{label} · {PROVIDERS[m.provider].label}",
                             m.input_per_mtok, m.output_per_mtok, m.vision, m.prices_as_of))
    return out


def resolve(us, ref: str) -> ModelInfo | None:  # noqa: ANN001
    return next((m for m in list_models(us) if m.ref == ref), None)


def model_dict(us, m: ModelInfo) -> dict:  # noqa: ANN001
    return {**asdict(m), "provider_label": PROVIDERS[m.provider].label, "configured": configured(us, m.provider),
            "priced": m.priced}


def meter_for(m: ModelInfo) -> claude.CostMeter:
    return claude.CostMeter(provider="claude" if m.provider == "anthropic" else m.provider,
                            prices_as_of=m.prices_as_of or claude.PRICES_AS_OF)


# ---------------------------------------------------------------------------
# Chamadas
# ---------------------------------------------------------------------------
def create(us, m: ModelInfo, system: str, content: list[dict] | str, schema: dict,  # noqa: ANN001
           meter: claude.CostMeter, is_canceled: Callable[[], bool] = lambda: False,
           on_chunk: Callable[[int], None] | None = None, temperature: float | None = None) -> str:
    """Uma chamada com saída JSON, no provedor do modelo. Conteúdo no formato de blocos da Anthropic."""
    if m.provider == "anthropic":
        return claude.create(claude.make_client(us.anthropic_api_key), m.id, system, content, schema, meter,
                             is_canceled, on_chunk)
    p = PROVIDERS[m.provider]
    return openai_compat.create(base_url(us, m.provider), api_key(us, m.provider), m.id, system, content, schema,
                                meter, provider=m.provider, provider_label=p.label, prices=m.prices,
                                temperature=temperature, is_canceled=is_canceled, on_chunk=on_chunk)


def chat(us, m: ModelInfo, meter: claude.CostMeter, is_canceled: Callable[[], bool],  # noqa: ANN001
         on_chunk: Callable[[int], None] | None = None, schema: dict | None = None) -> LLMCall:
    """Mesmo contrato do `ollama_chat`: (messages, temperature) → texto JSON."""
    if m.provider == "anthropic":
        return claude.claude_chat(us.anthropic_api_key, m.id, meter, is_canceled, on_chunk, schema)
    from .highlighter import SCHEMA

    def call(messages: list[dict], temperature: float) -> str:
        system = "\n\n".join(x["content"] for x in messages if x["role"] == "system")
        user = "\n\n".join(x["content"] for x in messages if x["role"] == "user")
        return create(us, m, system, user, schema or SCHEMA, meter, is_canceled, on_chunk, temperature)

    return call


# ---------------------------------------------------------------------------
# Catálogo (para adicionar modelos nas Configurações) — tudo grátis
# ---------------------------------------------------------------------------
def _per_mtok(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if f < 0 else round(f * 1_000_000, 6)


def openrouter_catalog() -> list[dict]:
    """Catálogo público do OpenRouter, com preço por token e modalidades de entrada (não precisa de chave)."""
    import datetime as dt

    import httpx

    r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20)
    r.raise_for_status()
    today = dt.date.today().isoformat()
    out = []
    for m in r.json().get("data", []):
        pricing = m.get("pricing") or {}
        modalities = (m.get("architecture") or {}).get("input_modalities") or []
        out.append({"id": m["id"], "label": m.get("name") or m["id"],
                    "input_per_mtok": _per_mtok(pricing.get("prompt")),
                    "output_per_mtok": _per_mtok(pricing.get("completion")),
                    "vision": "image" in modalities, "context": m.get("context_length"), "prices_as_of": today})
    return out


def catalog(us, provider: str) -> list[dict]:  # noqa: ANN001
    if provider == "openrouter":
        return openrouter_catalog()
    if provider == "anthropic":
        return [{"id": m, "label": claude.MODEL_LABELS[m], "input_per_mtok": p[0], "output_per_mtok": p[1],
                 "vision": True, "prices_as_of": claude.PRICES_AS_OF} for m, p in claude.PRICES.items()]
    models = openai_compat.list_models(base_url(us, provider), api_key(us, provider))
    ids = sorted({str(m["id"]).removeprefix("models/") for m in models})  # Gemini devolve "models/<id>"
    return [{"id": i, "label": i, "input_per_mtok": None, "output_per_mtok": None,
             "vision": PROVIDERS[provider].vision_default, "prices_as_of": ""} for i in ids]


def test_key(us, provider: str, key: str) -> dict:  # noqa: ANN001
    """Valida a chave sem gastar: OpenRouter → /key; demais compatíveis → /models. (Claude: ver /claude/test.)"""
    import httpx

    p = PROVIDERS[provider]
    url = base_url(us, provider)
    if not url:
        return {"ok": False, "message": "Informe o endereço da API (base URL) do provedor."}
    if not key:
        return {"ok": False, "message": f"Nenhuma chave do {p.label} informada."}
    try:
        if provider == "openrouter":
            r = httpx.get(f"{url}/key", headers={"Authorization": f"Bearer {key}"}, timeout=15)
            r.raise_for_status()
            d = r.json().get("data", {})
            left = d.get("limit_remaining")
            extra = f" Saldo do limite: US$ {left:.2f}." if isinstance(left, (int, float)) else ""
            return {"ok": True, "message": f"Chave válida ({p.label}).{extra}", "cost": {"usd": 0}}
        n = len(openai_compat.list_models(url, key))
        return {"ok": True, "message": f"Chave válida ({p.label}, {n} modelos disponíveis).", "cost": {"usd": 0}}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        msg = "Chave inválida." if code in (401, 403) else f"O {p.label} respondeu {code}."
        return {"ok": False, "message": msg, "detail": e.response.text[:500]}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Sem conexão com {url}.", "detail": str(e)}
