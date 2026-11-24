"""Detecção de destaques: LLM local (Ollama) + pós-processamento determinístico (seção 8.4)."""

from __future__ import annotations

import bisect
import json
import logging
import math
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np

from .templates import Template, get_template

log = logging.getLogger(__name__)

WINDOW_S = 8 * 60
OVERLAP_S = 60
PAUSE_S = 0.4  # pausa que conta como fim de frase
END_BREATH_S = 0.15
SNAP_RADIUS_S = 4.0  # distância máxima para "grudar" numa borda de frase
SENTENCE_END = (".", "?", "!", "…", '."', '?"', '!"')
WEIGHTS = {"gancho": 0.35, "completude": 0.25, "emocao": 0.25, "clareza": 0.15}

SYSTEM_PROMPT = """Você é um editor especialista em vídeos curtos virais (TikTok, Reels, Shorts).
Receberá a transcrição de um trecho de vídeo com timestamps.
Encontre os melhores momentos para virar cortes independentes de {min_s} a {max_s} segundos.
Um bom corte:
- começa com um GANCHO forte nos primeiros 3 segundos (pergunta, afirmação polêmica, número, promessa, conflito);
- é compreensível sozinho, sem contexto do resto do vídeo;
- tem começo, meio e fim (termina numa conclusão, punchline ou frase completa);
- tem emoção, humor, opinião forte, história ou informação valiosa.
Evite: introduções, pedidos de inscrição, trechos que dependem do que veio antes.
Use APENAS timestamps que existem na transcrição.
Para cada corte, preencha:
- start/end: segundos (copie dos timestamps da transcrição);
- title: título chamativo de até 60 caracteres, no idioma do vídeo;
- hook: a primeira frase do corte;
- reason: UMA FRASE explicando por que esse trecho prende a atenção (texto, nunca um número);
- scores: notas de 0 a 10 para gancho, emocao, clareza e completude. Seja exigente: 10 é raro.
{extra}
Responda somente no JSON pedido."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "scores": {
                        "type": "object",
                        "properties": {k: {"type": "integer", "minimum": 0, "maximum": 10} for k in WEIGHTS},
                        "required": list(WEIGHTS),
                    },
                },
                "required": ["start", "end", "title", "hook", "reason", "scores"],
            },
        }
    },
    "required": ["clips"],
}


class HighlightError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class Canceled(Exception):
    pass


# ---------------------------------------------------------------------------
# Palavras e bordas de frase
# ---------------------------------------------------------------------------
@dataclass
class Words:
    """Palavras achatadas do transcript + índices de início/fim de frase."""

    w: list[dict]
    starts: list[float] = field(default_factory=list)  # w[i].s
    sent_start_idx: list[int] = field(default_factory=list)
    sent_end_idx: list[int] = field(default_factory=list)
    sent_end_set: set[int] = field(default_factory=set)

    @classmethod
    def from_transcript(cls, transcript: dict) -> Words:
        words = [w for seg in transcript.get("segments", []) for w in seg.get("words", [])]
        words.sort(key=lambda x: x["s"])
        obj = cls(words, [x["s"] for x in words])
        n = len(words)
        for i, x in enumerate(words):
            prev_end = i == 0 or words[i - 1]["w"].endswith(SENTENCE_END) or x["s"] - words[i - 1]["e"] > PAUSE_S
            if prev_end:
                obj.sent_start_idx.append(i)
            this_end = i == n - 1 or x["w"].endswith(SENTENCE_END) or words[i + 1]["s"] - x["e"] > PAUSE_S
            if this_end:
                obj.sent_end_idx.append(i)
        obj.sent_end_set = set(obj.sent_end_idx)
        return obj

    def __len__(self) -> int:
        return len(self.w)

    def nearest_word_start(self, t: float) -> int:
        i = bisect.bisect_left(self.starts, t)
        cands = [j for j in (i - 1, i) if 0 <= j < len(self.w)]
        return min(cands, key=lambda j: abs(self.w[j]["s"] - t))

    def nearest_word_end(self, t: float) -> int:
        ends = [x["e"] for x in self.w]
        i = bisect.bisect_left(ends, t)
        cands = [j for j in (i - 1, i) if 0 <= j < len(self.w)]
        return min(cands, key=lambda j: abs(self.w[j]["e"] - t))

    def snap_start(self, t: float) -> int:
        """Início de frase mais próximo (até SNAP_RADIUS_S); senão, início de palavra mais próximo."""
        best = min(self.sent_start_idx, key=lambda i: abs(self.w[i]["s"] - t), default=None)
        if best is not None and abs(self.w[best]["s"] - t) <= SNAP_RADIUS_S:
            return best
        return self.nearest_word_start(t)

    def snap_end(self, t: float) -> int:
        best = min(self.sent_end_idx, key=lambda i: abs(self.w[i]["e"] - t), default=None)
        if best is not None and abs(self.w[best]["e"] - t) <= SNAP_RADIUS_S:
            return best
        return self.nearest_word_end(t)

    def end_time(self, i: int, duration: float) -> float:
        """Fim da palavra + respiro, sem invadir a próxima palavra nem passar do vídeo."""
        e = self.w[i]["e"]
        nxt = self.w[i + 1]["s"] - 0.02 if i + 1 < len(self.w) else math.inf
        return round(min(e + END_BREATH_S, max(e, nxt), duration), 3)


def fit_duration(words: Words, si: int, ei: int, min_s: float, max_s: float) -> tuple[int, int]:
    """Estende/encurta até bordas de frase para caber em [min_s, max_s]."""
    dur = lambda a, b: words.w[b]["e"] - words.w[a]["s"]  # noqa: E731
    if dur(si, ei) < min_s:
        # 1) estende o fim até a próxima borda de frase que atinja o mínimo
        for j in words.sent_end_idx:
            if j > ei and dur(si, j) >= min_s:
                if dur(si, j) <= max_s:
                    ei = j
                break
        # 2) ainda curto: recua o início por inícios de frase
        if dur(si, ei) < min_s:
            for j in reversed(words.sent_start_idx):
                if j < si and dur(j, ei) >= min_s:
                    if dur(j, ei) <= max_s:
                        si = j
                    break
        # 3) último recurso: palavras (ignora bordas de frase)
        while dur(si, ei) < min_s and ei + 1 < len(words) and dur(si, ei + 1) <= max_s:
            ei += 1
    if dur(si, ei) > max_s:
        ends = [j for j in words.sent_end_idx if si < j < ei and min_s <= dur(si, j) <= max_s]
        if ends:
            ei = ends[-1]
        else:
            while ei > si and dur(si, ei) > max_s:
                ei -= 1
    return si, ei


def prefer_sentence_end(words: Words, si: int, ei: int, min_s: float, max_s: float) -> int:
    """Se o fim caiu no meio de uma frase, troca pelo fim de frase mais próximo que respeite [min_s, max_s]."""
    if ei in words.sent_end_set:
        return ei
    target = words.w[ei]["e"]
    start = words.w[si]["s"]
    valid = [j for j in words.sent_end_idx if j > si and min_s <= words.w[j]["e"] - start <= max_s]
    return min(valid, key=lambda j: abs(words.w[j]["e"] - target)) if valid else ei


# ---------------------------------------------------------------------------
# Janelas e prompt
# ---------------------------------------------------------------------------
def make_windows(duration: float, size: float = WINDOW_S, overlap: float = OVERLAP_S) -> list[tuple[float, float]]:
    if duration <= size + overlap:
        return [(0.0, duration)]
    step = size - overlap
    n = math.ceil((duration - overlap) / step)
    return [(i * step, min(duration, i * step + size)) for i in range(n)]


LOUD_RATIO = 1.6  # trecho com RMS 60% acima da média do vídeo = "volume alto" (grito, risada, comemoração)


def segment_loudness(rms: np.ndarray | None, rms_mean: float, s: float, e: float) -> float:
    """Pico de volume do trecho relativo à média do vídeo (0 se não houver áudio)."""
    if rms is None or not len(rms) or rms_mean <= 0:
        return 0.0
    a, b = int(s / RMS_HOP_S), max(int(s / RMS_HOP_S) + 1, int(e / RMS_HOP_S))
    chunk = rms[a:b]
    return float(chunk.max()) / rms_mean if len(chunk) else 0.0


def transcript_lines(transcript: dict, t0: float, t1: float, rms: np.ndarray | None = None,
                     rms_mean: float = 0.0) -> str:
    """Linhas "[início–fim] texto". Com `rms`, marca falas com volume alto (pista de reação para a IA)."""
    lines = []
    for seg in transcript.get("segments", []):
        if seg["end"] <= t0 or seg["start"] >= t1 or not seg.get("words"):
            continue
        s, e = seg["words"][0]["s"], seg["words"][-1]["e"]
        text = " ".join(w["w"] for w in seg["words"])
        loud = rms is not None and segment_loudness(rms, rms_mean, s, e) >= LOUD_RATIO
        lines.append(f"[{s:.1f}–{e:.1f}] {text}" + (" [VOLUME ALTO]" if loud else ""))
    return "\n".join(lines)


def build_messages(lines: str, t0: float, t1: float, k: int, min_s: float, max_s: float, extra: str) -> list[dict]:
    extra_txt = f"Instruções específicas deste vídeo:\n{extra.strip()}" if extra.strip() else ""
    user = (f"Trecho de {t0:.0f}s a {t1:.0f}s do vídeo. Encontre até {k} cortes de {min_s:.0f} a {max_s:.0f} segundos.\n\n"
            f"TRANSCRIÇÃO:\n{lines}")
    return [{"role": "system", "content": SYSTEM_PROMPT.format(min_s=f"{min_s:.0f}", max_s=f"{max_s:.0f}", extra=extra_txt)},
            {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
LLMCall = Callable[[list[dict], float], str]


def ollama_chat(url: str, model: str, is_canceled: Callable[[], bool],
                on_chunk: Callable[[int], None] | None = None) -> LLMCall:
    """Retorna uma função (messages, temperature) → texto, com streaming para permitir cancelar."""
    base = url.rstrip("/")

    def call(messages: list[dict], temperature: float) -> str:
        body = {"model": model, "messages": messages, "stream": True, "format": SCHEMA,
                "options": {"temperature": temperature, "num_ctx": 8192}, "keep_alive": "5m"}
        parts: list[str] = []
        try:
            with httpx.stream("POST", f"{base}/api/chat", json=body,
                              timeout=httpx.Timeout(connect=5, read=300, write=30, pool=5)) as r:
                if r.status_code == 404:
                    raise HighlightError(f"O modelo {model} não está instalado no Ollama.", f"Rode: ollama pull {model}")
                if r.status_code >= 400:
                    r.read()
                    raise HighlightError("O Ollama recusou o pedido.", r.text[-1000:])
                for line in r.iter_lines():
                    if is_canceled():
                        raise Canceled()
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise HighlightError("Erro no Ollama.", str(msg["error"]))
                    parts.append(msg.get("message", {}).get("content", ""))
                    if on_chunk:
                        on_chunk(len(parts))
                    if msg.get("done"):
                        break
        except httpx.ConnectError as e:
            raise HighlightError(f"O Ollama não está respondendo em {url}. Verifique em Configurações.", str(e)) from e
        except httpx.TimeoutException as e:
            raise HighlightError("O Ollama demorou demais para responder.", str(e)) from e
        return "".join(parts)

    return call


def parse_candidates(raw: str) -> list[dict]:
    """Valida o JSON do LLM. Lança ValueError se não tiver o formato esperado."""
    data = json.loads(raw)
    clips = data.get("clips") if isinstance(data, dict) else None
    if not isinstance(clips, list):
        raise ValueError("JSON sem lista 'clips'")
    out = []
    for c in clips:
        if not isinstance(c, dict):
            continue
        try:
            start, end = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        scores_in = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        scores = {}
        for k in WEIGHTS:
            try:
                v = float(scores_in.get(k, 5))
            except (TypeError, ValueError):
                v = 5.0
            scores[k] = max(0.0, min(10.0, v / 10 if v > 10 else v))  # tolera escala 0-100
        reason = str(c.get("reason", "")).strip()
        if sum(ch.isalpha() for ch in reason) < 3:  # o modelo às vezes devolve um número no lugar do motivo
            reason = ""
        out.append({"start": start, "end": end, "title": str(c.get("title", "")).strip(),
                    "hook": str(c.get("hook", "")).strip(), "reason": reason, "scores": scores})
    return out


def ask_llm(llm: LLMCall, messages: list[dict]) -> list[dict]:
    """1ª tentativa com temperatura 0,3; se o JSON vier inválido, tenta de novo 1× com temperatura 0."""
    raw = llm(messages, 0.3)
    try:
        return parse_candidates(raw)
    except ValueError as e:
        log.warning("JSON inválido do LLM (%s); repetindo com temperatura 0", e)
    raw = llm(messages, 0.0)
    try:
        return parse_candidates(raw)
    except ValueError as e:
        raise HighlightError("O LLM não devolveu um JSON válido.", f"{e}\n{raw[:1500]}") from e


# ---------------------------------------------------------------------------
# Heurísticas de áudio/fala
# ---------------------------------------------------------------------------
RMS_HOP_S = 0.1


def rms_track(wav_path: Path) -> np.ndarray:
    """RMS a cada 100 ms (lido em blocos de 1 min)."""
    out: list[np.ndarray] = []
    with wave.open(str(wav_path), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        hop = int(rate * RMS_HOP_S)
        while True:
            raw = w.readframes(hop * 600)
            if not raw:
                break
            x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            n = len(x) // hop
            if n == 0:
                break
            out.append(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def _lin(x: float, x0: float, x1: float) -> float:
    return max(0.0, min(1.0, (x - x0) / (x1 - x0)))


def heuristic_score(words: Words, si: int, ei: int, rms: np.ndarray | None, rms_mean: float,
                    kind: str = "speech") -> dict:
    start, end = words.w[si]["s"], words.w[ei]["e"]
    dur = max(0.1, end - start)
    seg = words.w[si: ei + 1]
    # ritmo: 2,5–3,5 palavras/s é o ideal
    wps = len(seg) / dur
    rate = 1.0 if 2.5 <= wps <= 3.5 else (_lin(wps, 1.0, 2.5) if wps < 2.5 else 1 - _lin(wps, 3.5, 5.0))
    # silêncios longos (> 0,7 s entre palavras)
    gaps = sum(max(0.0, b["s"] - a["e"]) for a, b in zip(seg, seg[1:]) if b["s"] - a["e"] > 0.7)
    silence = 1 - min(1.0, 4 * gaps / dur)
    # energia: RMS do trecho vs média do vídeo (0,7× → 0, 1,3× → 1)
    energy = 0.5
    if rms is not None and len(rms) and rms_mean > 0:
        a, b = int(start / RMS_HOP_S), max(int(start / RMS_HOP_S) + 1, int(end / RMS_HOP_S))
        chunk = rms[a:b]
        if len(chunk):
            energy = _lin(float(chunk.mean()) / rms_mean, 0.7, 1.3)
    if kind == "reactions":
        # gameplay: o que importa é ter picos de volume (reações), não ritmo de fala constante
        peak = _lin(segment_loudness(rms, rms_mean, start, end), 1.3, 3.0) if rms is not None else 0.5
        h = 100 * (0.7 * peak + 0.3 * energy)
        return {"heuristica": round(h, 1), "energia": round(100 * energy), "pico": round(100 * peak),
                "palavras_s": round(wps, 2)}
    h = 100 * (energy + rate + silence) / 3
    return {"heuristica": round(h, 1), "energia": round(100 * energy), "ritmo": round(100 * rate),
            "silencio": round(100 * silence), "palavras_s": round(wps, 2)}


def llm_score(scores: dict) -> float:
    return 10 * sum(WEIGHTS[k] * scores[k] for k in WEIGHTS)  # 0-100


def overlap_ratio(a: dict, b: dict) -> float:
    inter = min(a["end_s"], b["end_s"]) - max(a["start_s"], b["start_s"])
    if inter <= 0:
        return 0.0
    return inter / min(a["end_s"] - a["start_s"], b["end_s"] - b["start_s"])


def remove_overlaps(clips: list[dict], max_ratio: float = 0.5) -> list[dict]:
    kept: list[dict] = []
    for c in sorted(clips, key=lambda c: c["score"], reverse=True):
        if all(overlap_ratio(c, k) <= max_ratio for k in kept):
            kept.append(c)
    return kept


def first_sentence(words: Words, si: int, ei: int, max_words: int = 18) -> str:
    out = []
    for i in range(si, ei + 1):
        out.append(words.w[i]["w"])
        if i in words.sent_end_set or len(out) >= max_words:
            break
    return " ".join(out)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def postprocess(cands: list[dict], words: Words, duration: float, min_s: float, max_s: float,
                rms: np.ndarray | None, heuristic: str = "speech", llm_weight: float = 0.75) -> list[dict]:
    rms_mean = float(rms.mean()) if rms is not None and len(rms) else 0.0
    out = []
    for c in cands:
        start = max(0.0, min(c["start"], duration))
        end = max(0.0, min(c["end"], duration))
        if end - start < 1:
            continue  # timestamps inválidos/invertidos
        si, ei = words.snap_start(start), words.snap_end(end)
        if ei <= si:
            continue
        si, ei = fit_duration(words, si, ei, min_s, max_s)
        ei = prefer_sentence_end(words, si, ei, min_s, max_s)
        start_s = round(words.w[si]["s"], 3)
        end_s = words.end_time(ei, duration)
        if end_s - start_s < min_s * 0.75:  # não deu para chegar perto do mínimo (vídeo curto/pouca fala)
            continue
        h = heuristic_score(words, si, ei, rms, rms_mean, heuristic)
        llm = llm_score(c["scores"])
        score = round(llm_weight * llm + (1 - llm_weight) * h["heuristica"], 1)
        out.append({
            "start_s": start_s, "end_s": end_s,
            "title": (c["title"] or first_sentence(words, si, ei, 8))[:60],
            "hook_text": first_sentence(words, si, ei),
            "reason": c["reason"][:1000],
            "score": score,
            "breakdown": {**{k: round(v, 1) for k, v in c["scores"].items()}, "llm": round(llm, 1), **h},
        })
    return out


def find_highlights(
    transcript: dict,
    duration: float,
    num_clips: int,
    min_s: float,
    max_s: float,
    extra_prompt: str,
    llm: LLMCall,
    wav_path: Path | None = None,
    on_window: Callable[[int, int], None] | None = None,
    is_canceled: Callable[[], bool] = lambda: False,
    template: Template | None = None,
) -> list[dict]:
    template = template or get_template(None)
    words = Words.from_transcript(transcript)
    if len(words) < 5:
        raise HighlightError("A transcrição tem pouquíssima fala — não há o que cortar.")
    spoken = words.w[-1]["e"] - words.w[0]["s"]
    if spoken < min_s:
        raise HighlightError(f"O vídeo tem só {spoken:.0f}s de fala; diminua a duração mínima dos cortes.")

    rms = rms_track(wav_path) if wav_path and wav_path.exists() else None
    rms_mean = float(rms.mean()) if rms is not None and len(rms) else 0.0
    prompt = "\n".join(p for p in (template.prompt, extra_prompt.strip()) if p)
    windows = make_windows(duration)
    # gameplay: a IA tende a escolher lances sobrepostos (mesma reação) → pede mais candidatos
    factor = 2.5 if template.heuristic == "reactions" else 1.5
    per_window = math.ceil(num_clips * factor / len(windows)) + 1
    cands: list[dict] = []
    for i, (t0, t1) in enumerate(windows):
        if is_canceled():
            raise Canceled()
        if on_window:
            on_window(i, len(windows))
        lines = transcript_lines(transcript, t0, t1, rms if template.loudness_hints else None, rms_mean)
        if not lines.strip():
            continue
        cands.extend(ask_llm(llm, build_messages(lines, t0, t1, per_window, min_s, max_s, prompt)))

    processed = postprocess(cands, words, duration, min_s, max_s, rms, template.heuristic, template.llm_weight)
    clips = remove_overlaps(processed)
    clips.sort(key=lambda c: c["score"], reverse=True)
    log.info("destaques (%s): %d candidatos do LLM → %d válidos → %d sem sobreposição", template.key, len(cands),
             len(processed), len(clips))
    return clips[:num_clips]
