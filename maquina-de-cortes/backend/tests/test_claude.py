"""Provedor Claude (pago): schema estrito, estimativas de custo e medição do custo real — sem chamar a API."""

from types import SimpleNamespace

import pytest

from app.services import claude, review
from app.services.highlighter import SCHEMA, HighlightError


def test_strict_schema_closes_objects_and_drops_numeric_limits():
    s = claude.strict_schema(SCHEMA)
    assert s["additionalProperties"] is False
    item = s["properties"]["clips"]["items"]
    assert item["additionalProperties"] is False
    scores = item["properties"]["scores"]
    assert scores["additionalProperties"] is False
    assert all("minimum" not in v and "maximum" not in v for v in scores["properties"].values())
    assert "minimum" in SCHEMA["properties"]["clips"]["items"]["properties"]["scores"]["properties"]["gancho"]  # original intacto


def test_usd_uses_table_prices():
    assert claude.usd("claude-opus-5-5", 1_000_000, 0) == pytest.approx(4.0)
    assert claude.usd("claude-haiku-5-5", 0, 1_000_000) == pytest.approx(0.5)


def test_estimate_analysis_scales_with_windows_and_has_worst_case():
    one = claude.estimate_analysis("claude-sonnet-5-5", 1, 3, 30_000)
    ten = claude.estimate_analysis("claude-sonnet-5-5", 10, 3, 300_000)
    assert ten["usd"] == pytest.approx(one["usd"] * 10, rel=1e-3)
    assert one["max_usd"] == pytest.approx(one["usd"] * 2, rel=1e-3)
    assert claude.estimate_analysis("claude-haiku-5-5", 10, 3, 300_000)["usd"] < ten["usd"]


def test_estimate_review_counts_frames():
    a = claude.estimate_review("claude-opus-5-5", 8, 600)
    b = claude.estimate_review("claude-opus-5-5", 16, 600)
    assert b["input_tokens"] - a["input_tokens"] == 8 * claude.IMAGE_TOKENS


def test_cost_meter_accumulates_real_usage():
    m = claude.CostMeter()
    m.add("claude-opus-5-5", SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=None,
                                             cache_creation_input_tokens=None))
    m.add("claude-opus-5-5", SimpleNamespace(input_tokens=1000, output_tokens=500))
    d = m.as_dict()
    assert d["calls"] == 2 and d["input_tokens"] == 2000 and d["output_tokens"] == 1000
    assert d["usd"] == pytest.approx((2000 * 4 + 1000 * 20) / 1e6, abs=1e-4)


class _FakeStream:
    def __init__(self, msg, chunks):
        self.msg, self.text_stream = msg, iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def _client(msg, chunks, seen):
    def stream(**kw):
        seen.update(kw)
        return _FakeStream(msg, chunks)

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def _msg(text, stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(model=model, stop_reason=stop, stop_details=None,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                           content=[SimpleNamespace(type="text", text=text)])


def test_create_sends_schema_effort_and_fallback_and_meters():
    seen: dict = {}
    m = claude.CostMeter()
    out = claude.create(_client(_msg('{"ok": true}'), ['{"ok"', ': true}'], seen), "claude-opus-5-5", "sys",
                        "oi", {"type": "object", "properties": {"ok": {"type": "boolean"}}}, m)
    assert out == '{"ok": true}'
    assert seen["output_config"]["effort"] == "medium"
    assert seen["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert seen["fallbacks"] == "default" and seen["betas"] == [claude.FALLBACK_BETA]
    assert "temperature" not in seen
    assert m.calls == 1


def test_create_haiku_has_no_fallback():
    seen: dict = {}
    claude.create(_client(_msg("{}", model="claude-haiku-5-5"), ["{}"], seen), "claude-haiku-5-5", "s", "u",
                  {"type": "object", "properties": {}}, claude.CostMeter())
    assert "fallbacks" not in seen


def test_create_refusal_raises_friendly_error_but_still_charges():
    m = claude.CostMeter()
    with pytest.raises(HighlightError):
        claude.create(_client(_msg("", stop="refusal"), [], {}), "claude-opus-5-5", "s", "u",
                      {"type": "object", "properties": {}}, m)
    assert m.calls == 1  # recusa também é cobrada


def test_claude_chat_splits_system_and_user():
    seen: dict = {}
    orig = claude.make_client
    claude.make_client = lambda key: _client(_msg('{"clips": []}'), ['{"clips": []}'], seen)
    try:
        llm = claude.claude_chat("", "claude-opus-5-5", claude.CostMeter(), lambda: False)
        assert llm([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], 0.3) == '{"clips": []}'
    finally:
        claude.make_client = orig
    assert seen["system"] == "S" and seen["messages"] == [{"role": "user", "content": "U"}]


def test_review_parse_normalizes():
    r = review.parse('{"verdict": "x", "summary": "ok", "issues": [{"t": -2, "kind": "?", "severity": "grave", '
                     '"text": "rosto cortado"}, {"t": 1, "kind": "legenda", "severity": "leve", "text": " "}]}')
    assert r["verdict"] == "warn"
    assert r["issues"] == [{"t": 0.0, "kind": "outro", "severity": "grave", "text": "rosto cortado"}]


def test_review_content_has_image_per_frame(tmp_path):
    f = tmp_path / "f01.jpg"
    f.write_bytes(b"\xff\xd8fake")
    content = review.build_content([(1.0, f), (3.0, f)], "[0.0s] oi", "T", 4.0)
    assert sum(1 for b in content if b["type"] == "image") == 2
    assert content[-1]["type"] == "text" and "oi" in content[-1]["text"]
