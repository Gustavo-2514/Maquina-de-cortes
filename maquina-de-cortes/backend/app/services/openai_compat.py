"""Cliente para APIs compatíveis com o Chat Completions da OpenAI (pago, opcional).

Um só caminho serve OpenAI, Google Gemini (endpoint de compatibilidade), OpenRouter, DeepSeek, xAI, Groq,
Mistral e qualquer servidor "compatível com OpenAI". Só usa `httpx` (já é dependência do app).

Os provedores aceitam subconjuntos diferentes dos parâmetros. Em vez de manter uma tabela por modelo,
a chamada se adapta: se a API recusar (HTTP 400/422) um parâmetro opcional que mandamos — saída por
JSON schema, temperatura, `stream_options` — ele é rebaixado/retirado e o pedido é repetido.
Um 400 é rejeitado antes de gerar qualquer token, então a repetição não é cobrada em dobro.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx

from .claude import CHARS_PER_TOKEN, CostMeter, strict_schema
from .highlighter import Canceled, HighlightError

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=15, read=300, write=60, pool=15)
APP_TITLE = "Maquina de Cortes"  # OpenRouter: identifica o app no painel (não é dado do usuário)


def to_openai_content(content: list[dict] | str) -> list[dict] | str:
    """Blocos no formato da Anthropic (texto + imagem base64) → formato da OpenAI (image_url com data URL)."""
    if isinstance(content, str):
        return content
    out: list[dict] = []
    for b in content:
        if b.get("type") == "image":
            src = b["source"]
            out.append({"type": "image_url",
                        "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
        else:
            out.append({"type": "text", "text": b.get("text", "")})
    return out


def _schema_hint(schema: dict) -> str:
    return ("\n\nResponda SOMENTE com um objeto JSON válido (sem markdown, sem texto fora do JSON) "
            f"que siga este JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}")


def _friendly(status: int, body: str, provider_label: str, model: str) -> HighlightError:
    low = body.lower()
    if status == 401:
        return HighlightError(f"A chave da API do {provider_label} é inválida.", "Confira em Configurações → IA paga.")
    if status == 402 or "insufficient" in low and ("credit" in low or "quota" in low or "balance" in low):
        return HighlightError(f"Sem créditos na conta do {provider_label}.", body[:1000])
    if status == 403:
        return HighlightError(f"A chave do {provider_label} não tem permissão para {model}.", body[:1000])
    if status == 404:
        return HighlightError(f"O {provider_label} não encontrou o modelo {model}.",
                              "Confira o ID do modelo em Configurações → IA paga.\n" + body[:800])
    if status == 429:
        return HighlightError(f"Limite de uso do {provider_label} atingido. Tente de novo em instantes.", body[:1000])
    if status in (400, 422):
        if "image" in low and ("support" in low or "vision" in low or "modalit" in low):
            return HighlightError(f"O modelo {model} não aceita imagens.",
                                  "Escolha um modelo com visão para a revisão visual.\n" + body[:800])
        return HighlightError(f"A API do {provider_label} recusou o pedido.", body[:1500])
    return HighlightError(f"Erro na API do {provider_label} ({status}).", body[:1500])


def _rejected_param(body: str, sent: dict) -> str | None:
    """Qual parâmetro opcional o provedor recusou (pela mensagem de erro), para rebaixá-lo."""
    low = body.lower()
    if "response_format" in sent and any(k in low for k in ("response_format", "json_schema", "json schema",
                                                             "structured output", "json_object", "json mode")):
        return "response_format"
    if "temperature" in sent and "temperature" in low:
        return "temperature"
    if "stream_options" in sent and ("stream_options" in low or "include_usage" in low):
        return "stream_options"
    if "usage" in sent and "usage" in low:
        return "usage"
    return None


def create(base_url: str, api_key: str, model: str, system: str, content: list[dict] | str, schema: dict,
           meter: CostMeter, *, provider: str = "openai", provider_label: str = "provedor",
           prices: tuple[float | None, float | None] = (None, None), temperature: float | None = None,
           is_canceled: Callable[[], bool] = lambda: False, on_chunk: Callable[[int], None] | None = None,
           client: httpx.Client | None = None) -> str:
    """Uma chamada com streaming (para poder cancelar) pedindo JSON. Registra o custo real no `meter`."""
    if not api_key:
        raise HighlightError(f"Nenhuma chave do {provider_label} configurada.", "Informe a chave em Configurações → IA paga.")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["X-Title"] = APP_TITLE
    user = to_openai_content(content)
    body: dict = {
        "model": model, "stream": True, "stream_options": {"include_usage": True},
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "resposta", "strict": True, "schema": strict_schema(schema)}},
    }
    if temperature is not None:
        body["temperature"] = temperature
    if provider == "openrouter":
        body["usage"] = {"include": True}  # devolve o custo real em US$ (usage.cost)
    json_mode = "schema"  # → "object" → "none" conforme o provedor recusar

    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        for _attempt in range(6):
            sys_text = system if json_mode == "schema" else system + _schema_hint(schema)
            body["messages"] = [{"role": "system", "content": sys_text}, {"role": "user", "content": user}]
            try:
                with http.stream("POST", url, headers=headers, json=body) as r:
                    if r.status_code >= 400:
                        err = r.read().decode("utf-8", "replace")
                        bad = _rejected_param(err, body) if r.status_code in (400, 422) else None
                        if bad == "response_format" and json_mode == "schema":
                            json_mode = "object"
                            body["response_format"] = {"type": "json_object"}
                            continue
                        if bad:
                            if bad == "response_format":
                                json_mode = "none"
                            body.pop(bad, None)
                            log.info("%s recusou %s; repetindo sem", provider, bad)
                            continue
                        raise _friendly(r.status_code, err, provider_label, model)
                    return _consume(r, model, meter, prices, sys_text, user, provider_label, is_canceled, on_chunk)
            except httpx.TimeoutException as e:
                raise HighlightError(f"O {provider_label} demorou demais para responder.", str(e)) from e
            except httpx.HTTPError as e:
                raise HighlightError(f"Sem conexão com a API do {provider_label}.", str(e)) from e
        raise HighlightError(f"A API do {provider_label} recusou todos os formatos de pedido.", "")
    finally:
        if own:
            http.close()


def _consume(r: httpx.Response, model: str, meter: CostMeter, prices: tuple[float | None, float | None],
             sys_text: str, user: list[dict] | str, provider_label: str,
             is_canceled: Callable[[], bool], on_chunk: Callable[[int], None] | None) -> str:
    parts: list[str] = []
    usage: dict | None = None
    finish: str | None = None
    served_model = model
    for line in r.iter_lines():
        if is_canceled():
            raise Canceled()
        if not line.startswith("data:"):
            continue  # comentários de keep-alive (": OPENROUTER PROCESSING") e linhas vazias
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("error"):
            e = chunk["error"]
            raise HighlightError(f"Erro na API do {provider_label}.", str(e.get("message", e) if isinstance(e, dict) else e))
        served_model = chunk.get("model") or served_model
        if chunk.get("usage"):
            usage = chunk["usage"]
        for ch in chunk.get("choices") or []:
            piece = (ch.get("delta") or {}).get("content")
            if piece:
                parts.append(piece)
                if on_chunk:
                    on_chunk(len(parts))
            finish = ch.get("finish_reason") or finish
    text = "".join(parts)
    _meter(meter, served_model, usage, prices, sys_text, user, text)
    if finish == "length":
        raise HighlightError(f"A resposta do {provider_label} foi cortada (limite de tokens).", "")
    if finish == "content_filter":
        raise HighlightError(f"O {provider_label} recusou analisar este trecho (filtro de conteúdo).", "")
    return strip_fences(text)


def strip_fences(raw: str) -> str:
    """Sem saída estruturada, alguns modelos embrulham o JSON em ```json … ``` ou pensam em <think>…</think>."""
    s = raw.strip()
    if s.startswith("<think>") and "</think>" in s:
        s = s.split("</think>", 1)[1].strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0]
    return s.strip()


def _meter(meter: CostMeter, model: str, usage: dict | None, prices: tuple[float | None, float | None],
           sys_text: str, user: list[dict] | str, text: str) -> None:
    approx = not usage
    if usage:
        inp = int(usage.get("prompt_tokens") or 0)
        out = int(usage.get("completion_tokens") or 0)
    else:  # provedor não mandou o uso: estimativa pelo tamanho do texto (imagens ≈ 450 tokens cada)
        chars = len(sys_text) + (len(user) if isinstance(user, str) else
                                 sum(len(b.get("text", "")) for b in user))
        n_img = 0 if isinstance(user, str) else sum(1 for b in user if b.get("type") == "image_url")
        inp = round(chars / CHARS_PER_TOKEN) + n_img * 450
        out = round(len(text) / CHARS_PER_TOKEN)
    cost: float | None
    if usage and isinstance(usage.get("cost"), (int, float)):
        cost = float(usage["cost"])  # OpenRouter: custo real cobrado
    elif prices[0] is not None and prices[1] is not None:
        cost = (inp * prices[0] + out * prices[1]) / 1_000_000
    else:
        cost = None
    meter.add_tokens(model, inp, out, cost, approx=approx)
    log.info("%s %s: %s tokens entrada, %s saída, US$ %s", meter.provider, model, inp, out, cost)


def list_models(base_url: str, api_key: str, timeout: float = 15) -> list[dict]:
    """GET /models (grátis). Valida a chave e lista os IDs disponíveis."""
    r = httpx.get(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    return [m for m in items or [] if isinstance(m, dict) and m.get("id")]
