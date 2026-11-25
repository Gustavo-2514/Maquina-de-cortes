"""IA paga por chave: refs de modelo, roteamento e o cliente compatível com OpenAI — sem rede (MockTransport)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AiModel, UserSettings, load_user_settings, save_user_settings
from app.services import ai, claude, openai_compat
from app.services.highlighter import Canceled, HighlightError


def _us(**kw) -> UserSettings:
    return UserSettings(**kw)


def test_refs_keep_bare_claude_ids_and_prefix_the_rest():
    assert ai.split_ref("claude-opus-5-5") == ("anthropic", "claude-opus-5-5")
    assert ai.split_ref("openrouter:openai/gpt-x") == ("openrouter", "openai/gpt-x")
    assert ai.make_ref("openrouter", "openai/gpt-x") == "openrouter:openai/gpt-x"
    assert ai.make_ref("anthropic", "claude-haiku-5-5") == "claude-haiku-5-5"
    assert ai.split_ref("nada:x") == ("", "nada:x")


def test_list_models_includes_claude_and_user_models():
    us = _us(ai_models=[AiModel(provider="openrouter", id="google/gemini-x", label="Gemini X",
                                input_per_mtok=1.0, output_per_mtok=2.0, vision=True),
                        AiModel(provider="openai", id="gpt-x"),
                        AiModel(provider="inexistente", id="y")])
    refs = [m.ref for m in ai.list_models(us)]
    assert refs[:3] == list(claude.PRICES)
    assert "openrouter:google/gemini-x" in refs and "openai:gpt-x" in refs
    assert not any(r.endswith(":y") for r in refs)
    gpt = ai.resolve(us, "openai:gpt-x")
    assert gpt and not gpt.priced


def test_review_model_migrates_from_claude_model():
    assert UserSettings(claude_model="claude-haiku-5-5").review_model == "claude-haiku-5-5"
    assert UserSettings(review_model="openai:gpt-x").review_model == "openai:gpt-x"


def test_configured_uses_saved_key_or_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not ai.configured(_us(), "openai")
    assert ai.configured(_us(api_keys={"openai": "sk-1"}), "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert ai.api_key(_us(), "openai") == "sk-env"
    assert not ai.configured(_us(api_keys={"custom": "k"}), "custom")  # custom sem base URL
    assert ai.configured(_us(api_keys={"custom": "k"}, custom_base_url="http://x/v1"), "custom")


def test_estimate_without_prices_has_no_usd():
    e = claude.estimate_analysis("openai:gpt-x", 2, 3, 6000, prices=(None, None))
    assert e["usd"] is None and e["max_usd"] is None and e["input_tokens"] == 2000
    p = claude.estimate_analysis("openai:gpt-x", 2, 3, 6000, prices=(1.0, 2.0))
    assert p["usd"] == pytest.approx((2000 * 1 + p["output_tokens"] * 2) / 1e6, abs=1e-4)


def test_image_blocks_convert_to_data_urls():
    out = openai_compat.to_openai_content([
        {"type": "text", "text": "Quadro"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}])
    assert out == [{"type": "text", "text": "Quadro"},
                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]


def _sse(*chunks: dict) -> bytes:
    return b"".join(f"data: {json.dumps(c)}\n\n".encode() for c in chunks) + b": keepalive\n\ndata: [DONE]\n\n"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def test_streaming_meters_with_table_prices():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer sk-1"
        return httpx.Response(200, content=_sse(
            {"model": "gpt-x", "choices": [{"delta": {"content": '{"ok"'}}]},
            {"choices": [{"delta": {"content": ": true}"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}))

    m = claude.CostMeter(provider="openai")
    out = openai_compat.create("https://api.x/v1", "sk-1", "gpt-x", "sys", "oi", SCHEMA, m,
                               prices=(2.0, 8.0), temperature=0.3, client=_client(handler))
    assert out == '{"ok": true}'
    body = seen[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert body["temperature"] == 0.3 and body["stream"] is True
    d = m.as_dict()
    assert d["provider"] == "openai" and d["input_tokens"] == 1000 and d["output_tokens"] == 500
    assert d["usd"] == pytest.approx((1000 * 2 + 500 * 8) / 1e6)
    assert "priced" not in d


def test_falls_back_when_provider_rejects_json_schema_and_temperature():
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        b = json.loads(req.content)
        bodies.append(b)
        if b.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        if "temperature" in b:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature'"}})
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": '```json\n{"ok": true}\n```'}}]}))

    m = claude.CostMeter(provider="deepseek")
    out = openai_compat.create("https://api.x/v1", "k", "m", "sys", "oi", SCHEMA, m, temperature=0.3,
                               client=_client(handler))
    assert out == '{"ok": true}'  # cercas de markdown removidas
    assert bodies[1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in bodies[1]["messages"][0]["content"]  # schema vai no prompt quando não é imposto
    assert "temperature" not in bodies[-1]
    d = m.as_dict()
    assert d["calls"] == 1 and d["approx"] is True and d["priced"] is False  # sem usage e sem preço


def test_openrouter_uses_reported_cost_and_sends_title():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["x-title"]
        assert json.loads(req.content)["usage"] == {"include": True}
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0123}}))

    m = claude.CostMeter(provider="openrouter")
    openai_compat.create("https://openrouter.ai/api/v1", "k", "a/b", "s", "u", SCHEMA, m, provider="openrouter",
                         client=_client(handler))
    assert m.as_dict()["usd"] == pytest.approx(0.0123)


@pytest.mark.parametrize("status,text", [(401, "inválida"), (402, "créditos"), (404, "não encontrou"), (429, "Limite")])
def test_http_errors_are_friendly(status, text):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "x"}})

    with pytest.raises(HighlightError, match=text):
        openai_compat.create("https://api.x/v1", "k", "m", "s", "u", SCHEMA, claude.CostMeter(),
                             provider_label="OpenAI", client=_client(handler))


def test_missing_key_and_cancel():
    with pytest.raises(HighlightError, match="Nenhuma chave"):
        openai_compat.create("https://api.x/v1", "", "m", "s", "u", SCHEMA, claude.CostMeter())

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse({"choices": [{"delta": {"content": "{"}}]}))

    with pytest.raises(Canceled):
        openai_compat.create("https://api.x/v1", "k", "m", "s", "u", SCHEMA, claude.CostMeter(),
                             is_canceled=lambda: True, client=_client(handler))


def test_length_cutoff_raises_but_still_meters():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": '{"ok'}, "finish_reason": "length"}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 4}}))

    m = claude.CostMeter()
    with pytest.raises(HighlightError, match="cortada"):
        openai_compat.create("https://api.x/v1", "k", "m", "s", "u", SCHEMA, m, prices=(1, 1),
                             client=_client(handler))
    assert m.calls == 1


def test_chat_routes_non_claude_to_compat(monkeypatch):
    got: dict = {}

    def fake_create(base_url, key, model, system, content, schema, meter, **kw):
        got.update(base_url=base_url, key=key, model=model, system=system, content=content, **kw)
        return '{"clips": []}'

    monkeypatch.setattr(openai_compat, "create", fake_create)
    us = _us(api_keys={"gemini": "AIza1"}, ai_models=[AiModel(provider="gemini", id="gemini-x")])
    info = ai.resolve(us, "gemini:gemini-x")
    llm = ai.chat(us, info, ai.meter_for(info), lambda: False)
    assert llm([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], 0.3) == '{"clips": []}'
    assert got["base_url"].startswith("https://generativelanguage.googleapis.com")
    assert got["key"] == "AIza1" and got["model"] == "gemini-x" and got["temperature"] == 0.3
    assert got["system"] == "S" and got["content"] == "U"


def test_settings_mask_every_provider_key():
    before = load_user_settings()
    try:
        with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
            s = c.get("/api/system/settings").json()
            s["api_keys"] = {"openrouter": "sk-or-abcdef1234", "openai": ""}
            r = c.put("/api/system/settings", json=s).json()
            assert r["api_keys"] == {"openrouter": "••••1234"}
            assert load_user_settings().api_keys == {"openrouter": "sk-or-abcdef1234"}
            # reenviar mascarada mantém a salva
            c.put("/api/system/settings", json=r)
            assert load_user_settings().api_keys == {"openrouter": "sk-or-abcdef1234"}
            models = c.get("/api/system/ai/models").json()["models"]
            assert any(m["ref"] == "claude-opus-5-5" for m in models)
            prov = {p["key"]: p for p in c.get("/api/system/ai/providers").json()["providers"]}
            assert prov["openrouter"]["configured"] is True
    finally:
        save_user_settings(before)
