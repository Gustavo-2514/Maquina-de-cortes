"""Fase 3: pós-processamento determinístico dos destaques (LLM mockado)."""

from __future__ import annotations

import json

import pytest

from app.services import highlighter as hl


def make_transcript(n_sentences: int = 40, words_per: int = 8, wdur: float = 0.3, gap: float = 0.05,
                    pause: float = 0.6) -> dict:
    """Frases de `words_per` palavras terminadas em ponto, separadas por pausa."""
    segs, t = [], 0.0
    for si in range(n_sentences):
        words = []
        for wi in range(words_per):
            text = f"p{si}_{wi}" + ("." if wi == words_per - 1 else "")
            words.append({"w": text, "s": round(t, 3), "e": round(t + wdur, 3), "p": 0.9})
            t += wdur + gap
        t += pause
        segs.append({"id": si, "start": words[0]["s"], "end": words[-1]["e"],
                     "text": " ".join(w["w"] for w in words), "words": words})
    return {"language": "pt", "segments": segs}


SENT_LEN = 8 * (0.3 + 0.05) + 0.6  # período de uma frase (palavras + pausa) = 3.4 s


def cand(start, end, g=8, e=7, c=7, cl=8, title="T"):
    return {"start": start, "end": end, "title": title, "hook": "", "reason": "r",
            "scores": {"gancho": g, "emocao": e, "clareza": cl, "completude": c}}


@pytest.fixture
def words():
    return hl.Words.from_transcript(make_transcript())


def test_sentence_boundaries(words):
    assert words.sent_start_idx[:3] == [0, 8, 16]
    assert words.sent_end_idx[:3] == [7, 15, 23]


def test_snap_to_sentences(words):
    # 1.0 s está no meio da 1ª frase → início de frase mais próximo é 0.0
    assert words.snap_start(1.0) == 0
    # perto do início da 2ª frase
    assert words.w[words.snap_start(SENT_LEN + 0.5)]["s"] == pytest.approx(SENT_LEN, abs=0.01)
    # fim: grudar no fim de frase mais próximo
    i = words.snap_end(SENT_LEN * 2 - 1.0)
    assert words.w[i]["w"].endswith(".")


def test_end_breath_does_not_cross_next_word(words):
    i = words.sent_end_idx[0]
    end = words.end_time(i, 9999)
    assert end == pytest.approx(words.w[i]["e"] + hl.END_BREATH_S)
    # palavra no meio da frase: próxima palavra começa 0,05 s depois → não pode invadir
    assert words.end_time(0, 9999) < words.w[1]["s"]


def test_fit_duration_extends_and_shrinks(words):
    si, ei = hl.fit_duration(words, 0, 7, min_s=20, max_s=40)  # 1 frase (~2.75 s) → estende
    dur = words.w[ei]["e"] - words.w[si]["s"]
    assert 20 <= dur <= 40 and words.w[ei]["w"].endswith(".")
    si, ei = hl.fit_duration(words, 0, len(words) - 1, min_s=20, max_s=40)  # tudo → encurta
    dur = words.w[ei]["e"] - words.w[si]["s"]
    assert 20 <= dur <= 40 and words.w[ei]["w"].endswith(".")


def test_postprocess_snaps_clamps_and_scores(words):
    out = hl.postprocess([cand(1.0, 25.0), cand(500, 400), cand(-5, 30)], words, duration=200,
                         min_s=20, max_s=60, rms=None)
    assert len(out) == 2  # o invertido é descartado
    c = out[0]
    assert c["start_s"] == 0.0
    assert 20 <= c["end_s"] - c["start_s"] <= 60.2
    # fim = fim de frase + respiro
    assert any(abs(c["end_s"] - (w["e"] + hl.END_BREATH_S)) < 1e-6 for w in words.w if w["w"].endswith("."))
    llm = 10 * (0.35 * 8 + 0.25 * 7 + 0.25 * 7 + 0.15 * 8)
    assert c["breakdown"]["llm"] == pytest.approx(llm, abs=0.1)
    assert c["score"] == pytest.approx(0.75 * llm + 0.25 * c["breakdown"]["heuristica"], abs=0.1)
    assert c["hook_text"].startswith("p0_0") and c["hook_text"].endswith(".")


def test_remove_overlaps_keeps_best():
    a = {"start_s": 0, "end_s": 30, "score": 70}
    b = {"start_s": 10, "end_s": 40, "score": 90}  # sobrepõe 20/30 = 67% → sai o de menor nota
    c = {"start_s": 25, "end_s": 60, "score": 50}  # sobrepõe b em 15/30 = 50% → fica
    kept = hl.remove_overlaps([a, b, c])
    assert [k["score"] for k in kept] == [90, 50]


def test_windows():
    assert hl.make_windows(300) == [(0.0, 300)]
    w = hl.make_windows(3600)
    assert w[0] == (0, 480) and w[1][0] == 420  # 1 min de sobreposição
    assert w[-1][1] == 3600
    assert all(b - a <= 480 for a, b in w)


def test_parse_candidates_tolerant():
    raw = json.dumps({"clips": [cand(1, 30), {"start": "x"}, {**cand(5, 40), "scores": {"gancho": 90}}]})
    out = hl.parse_candidates(raw)
    assert len(out) == 2
    assert out[1]["scores"]["gancho"] == 9  # escala 0-100 convertida
    assert out[1]["scores"]["emocao"] == 5  # ausente → neutro
    with pytest.raises(ValueError):
        hl.parse_candidates("isso não é json")
    with pytest.raises(ValueError):
        hl.parse_candidates('{"outra": 1}')


def test_ask_llm_retries_with_temperature_zero():
    calls = []

    def llm(messages, temperature):
        calls.append(temperature)
        return "lixo{" if len(calls) == 1 else json.dumps({"clips": [cand(1, 30)]})

    assert len(hl.ask_llm(llm, [])) == 1
    assert calls == [0.3, 0.0]

    with pytest.raises(hl.HighlightError):
        hl.ask_llm(lambda m, t: "lixo", [])


def test_find_highlights_end_to_end():
    t = make_transcript(n_sentences=300)  # ~17 min → várias janelas
    duration = t["segments"][-1]["end"] + 1
    seen_windows = []

    def llm(messages, temperature):
        user = messages[1]["content"]
        assert "TRANSCRIÇÃO" in user and "Encontre até" in user
        t0 = float(user.split("Trecho de ")[1].split("s")[0])
        seen_windows.append(t0)
        # dois candidatos por janela, um deles repetido entre janelas (sobreposição)
        return json.dumps({"clips": [cand(t0 + 10, t0 + 45, g=9), cand(t0 + 10.5, t0 + 44, g=5),
                                     cand(t0 + 100, t0 + 130, g=6)]})

    clips = hl.find_highlights(t, duration, num_clips=5, min_s=20, max_s=60, extra_prompt="foque no humor",
                               llm=llm)
    assert len(seen_windows) == len(hl.make_windows(duration)) > 1
    assert len(clips) == 5
    scores = [c["score"] for c in clips]
    assert scores == sorted(scores, reverse=True)
    for a in clips:
        assert 20 <= a["end_s"] - a["start_s"] <= 60.2
        for b in clips:
            if a is not b:
                assert hl.overlap_ratio(a, b) <= 0.5


def test_find_highlights_resumes_from_failed_window(tmp_path):
    t = make_transcript(n_sentences=300)
    duration = t["segments"][-1]["end"] + 1
    n = len(hl.make_windows(duration))
    assert n > 2
    calls: list[float] = []
    fail_at = {"t0": hl.make_windows(duration)[2][0]}

    def llm(messages, temperature):
        t0 = float(messages[1]["content"].split("Trecho de ")[1].split("s")[0])
        calls.append(t0)
        if t0 == fail_at["t0"]:
            return '{"clips": [{"start": 1, "title": "sem fim'  # JSON cortado, como no loop do modelo
        return json.dumps({"clips": [cand(t0 + 10, t0 + 45)]})

    cache = tmp_path / "cache"
    with pytest.raises(hl.HighlightError):
        hl.find_highlights(t, duration, 5, 20, 60, "", llm=llm, cache_dir=cache, cache_tag="m")
    assert len(list(cache.glob("*.json"))) == 2  # trechos 1 e 2 ficaram guardados

    calls.clear()
    fail_at["t0"] = -1
    clips = hl.find_highlights(t, duration, 5, 20, 60, "", llm=llm, cache_dir=cache, cache_tag="m")
    assert clips
    assert len(calls) == n - 2  # retomou do trecho que falhou

    calls.clear()  # outro modelo → não reaproveita
    hl.find_highlights(t, duration, 5, 20, 60, "", llm=llm, cache_dir=cache, cache_tag="outro")
    assert len(calls) == n


def test_pick_num_ctx_only_grows_when_needed():
    asked = []

    def limit():
        asked.append(1)
        return 32768

    assert hl.pick_num_ctx(3000, limit) == hl.OLLAMA_BASE_CTX
    assert not asked  # cabe no padrão → nem consulta o modelo
    ctx = hl.pick_num_ctx(10_300, limit)  # o trecho que falhava (~9-10 mil tokens)
    assert asked and ctx >= 10_300 + hl.OLLAMA_MAX_TOKENS and ctx % hl.OLLAMA_CTX_STEP == 0 and ctx <= 32768
    with pytest.raises(hl.PromptTooLong):
        hl.pick_num_ctx(31_000, limit)


def test_estimate_tokens_is_conservative():
    # medido no Ollama: 16 653 caracteres de transcrição com timestamps = 9 122 tokens
    msgs = [{"role": "system", "content": "x" * 3000}, {"role": "user", "content": "y" * 13_653}]
    assert hl.estimate_tokens(msgs) >= 9122


def test_ollama_context_limit_reads_model_info(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"model_info": {"general.architecture": "qwen2", "qwen2.context_length": 32768}}

    hl._CTX_LIMITS.clear()
    monkeypatch.setattr(hl.httpx, "post", lambda *a, **k: R())
    assert hl.ollama_context_limit("http://x", "qwen2.5:7b") == 32768
    hl._CTX_LIMITS.clear()


def test_find_highlights_splits_window_that_does_not_fit(tmp_path):
    t = make_transcript(n_sentences=300)
    duration = t["segments"][-1]["end"] + 1
    windows = hl.make_windows(duration)
    big = windows[1]
    spans: list[tuple[float, float]] = []

    def llm(messages, temperature):
        head = messages[1]["content"].split("Trecho de ")[1]
        t0 = float(head.split("s")[0])
        t1 = float(head.split(" a ")[1].split("s")[0])
        spans.append((t0, t1))
        if t1 - t0 > (big[1] - big[0]) * 0.9 and round(t0) == round(big[0]):
            raise hl.PromptTooLong("grande demais")
        return json.dumps({"clips": [cand(t0 + 10, t0 + 45)]})

    clips = hl.find_highlights(t, duration, 5, 20, 60, "", llm=llm, cache_dir=tmp_path / "c", cache_tag="m")
    assert clips
    halves = [s for s in spans if big[0] - 1 <= s[0] and s[1] <= big[1] + 1 and s[1] - s[0] < big[1] - big[0]]
    assert len(halves) == 2  # o trecho grande virou dois menores
    assert halves[0][0] <= big[0] + 1 and halves[1][1] >= big[1] - 1  # cobrem o trecho inteiro
    assert halves[0][1] > halves[1][0]  # com sobreposição


def test_find_highlights_gives_up_when_window_cannot_shrink():
    t = make_transcript(n_sentences=60)
    duration = t["segments"][-1]["end"] + 1

    def llm(messages, temperature):
        raise hl.PromptTooLong("grande demais")

    with pytest.raises(hl.PromptTooLong):
        hl.find_highlights(t, duration, 3, 20, 60, "", llm=llm)


def test_find_highlights_too_little_speech():
    t = make_transcript(n_sentences=2)
    with pytest.raises(hl.HighlightError):
        hl.find_highlights(t, 10, 5, 20, 60, "", llm=lambda m, x: '{"clips": []}')


def test_extra_prompt_in_system():
    msgs = hl.build_messages("[0.0–1.0] oi", 0, 60, 3, 20, 60, "foque nas partes engraçadas")
    assert "foque nas partes engraçadas" in msgs[0]["content"]
    assert "de 20 a 60 segundos" in msgs[0]["content"]


def test_far_end_moves_to_sentence_end(words):
    # fim pedido no meio de uma frase e longe (> raio) de qualquer fim de frase: palavras de 2 s
    t = {"segments": [{"id": 0, "start": 0, "end": 200, "text": "", "words": [
        {"w": f"w{i}" + ("." if i in (9, 19, 29) else ""), "s": i * 2.0, "e": i * 2.0 + 1.9, "p": 1} for i in range(40)]}]}
    W = hl.Words.from_transcript(t)
    out = hl.postprocess([cand(0, 50.0)], W, duration=100, min_s=20, max_s=60, rms=None)
    assert len(out) == 1
    assert out[0]["end_s"] in (W.end_time(19, 100), W.end_time(29, 100))  # fim de frase, não w24
