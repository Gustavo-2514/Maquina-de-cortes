"""Geração de legendas .ass palavra por palavra (seção 8.6).

Entrada: palavras do transcript (tempos absolutos) + intervalo do corte + estilo.
Saída: arquivo ASS em 1080×1920 com tempos relativos ao início do corte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PLAY_W, PLAY_H = 1080, 1920
MAX_LINE_CHARS = 18
LINE_BREAK_PAUSE_S = 0.35
HOLD_GAP_S = 0.6  # se a próxima linha vem logo, a atual fica na tela até ela
HOLD_AFTER_S = 0.25  # senão, segura um pouco depois da última palavra
BREAK_PUNCT = (".", ",", "?", "!", "…", ";", ":")


@dataclass
class Style:
    font: str = "Montserrat ExtraBold"
    font_size: int = 92
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    outline_color: str = "#000000"
    outline_px: float = 6
    shadow_px: float = 0
    uppercase: bool = True
    words_per_line: int = 2
    position_y: float = 0.68
    animation: str = "highlight"  # highlight | pop | karaoke | none

    @classmethod
    def from_obj(cls, obj: Any) -> Style:
        return cls(**{k: getattr(obj, k) for k in cls.__dataclass_fields__ if hasattr(obj, k)})

    def merged(self, overrides: dict | None) -> Style:
        """Ajustes do editor por cima do preset (só campos conhecidos, com tipos/limites sãos)."""
        if not overrides:
            return self
        data = dict(self.__dict__)
        casts = {"font": str, "font_size": int, "primary_color": str, "highlight_color": str, "outline_color": str,
                 "outline_px": float, "shadow_px": float, "uppercase": bool, "words_per_line": int,
                 "position_y": float, "animation": str}
        for k, v in overrides.items():
            if k in casts and v is not None:
                try:
                    data[k] = casts[k](v)
                except (TypeError, ValueError):
                    continue
        data["font_size"] = max(20, min(240, data["font_size"]))
        data["words_per_line"] = max(1, min(4, data["words_per_line"]))
        data["position_y"] = max(0.05, min(0.95, data["position_y"]))
        if data["animation"] not in ("highlight", "pop", "karaoke", "none"):
            data["animation"] = self.animation
        for c in ("primary_color", "highlight_color", "outline_color"):
            h = str(data[c]).lstrip("#")
            if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
                data[c] = getattr(self, c)
        return Style(**data)


@dataclass
class ClipOverrides:
    words: dict[str, str]
    style: dict
    title_until: float | None


def parse_overrides(raw: str) -> ClipOverrides:
    """caption_overrides_json → partes. Aceita o formato antigo (dict plano de palavras)."""
    import json

    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if "words" in data or "style" in data or "title_until" in data:
        words = data.get("words") if isinstance(data.get("words"), dict) else {}
        style = data.get("style") if isinstance(data.get("style"), dict) else {}
        tu = data.get("title_until")
        title_until = float(tu) if isinstance(tu, (int, float)) and tu > 0 else None
    else:
        words, style, title_until = data, {}, None
    return ClipOverrides({str(k): str(v) for k, v in words.items()}, style, title_until)


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB → &HAABBGGRR (o ASS usa BGR, e alpha 00 = opaco)."""
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"cor inválida: {hex_rgb}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def inline_color(hex_rgb: str) -> str:
    """Override inline: {\\c&HBBGGRR&}."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape_text(s: str) -> str:
    # chaves abrem blocos de override; barra invertida inicia comandos
    return s.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def clip_words(words: list[dict], start: float, end: float, overrides: dict[str, str] | None = None) -> list[dict]:
    """Palavras dentro do corte, com tempos relativos e correções aplicadas.

    `overrides` mapeia o início absoluto da palavra (f"{s:.3f}") → texto corrigido no editor.
    """
    overrides = overrides or {}
    out = []
    dur = end - start
    for w in words:
        if w["e"] <= start + 0.02 or w["s"] >= end - 0.02:
            continue
        text = overrides.get(f"{w['s']:.3f}", w["w"]).strip()
        if not text:
            continue  # palavra apagada pelo usuário
        out.append({"w": text, "s": round(max(0.0, w["s"] - start), 3), "e": round(min(dur, w["e"] - start), 3)})
    return out


def group_lines(words: list[dict], words_per_line: int, max_chars: int = MAX_LINE_CHARS) -> list[list[dict]]:
    """Quebra em linhas: N palavras, pontuação, pausas > 0,35 s ou linha longa demais."""
    lines: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            prev = cur[-1]
            chars = sum(len(x["w"]) for x in cur) + len(cur) + len(w["w"])
            if (len(cur) >= words_per_line or prev["w"].endswith(BREAK_PUNCT)
                    or w["s"] - prev["e"] > LINE_BREAK_PAUSE_S or chars > max_chars):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _line_text(line: list[dict], style: Style, current: int | None) -> str:
    parts = []
    hl = inline_color(style.highlight_color)
    base = inline_color(style.primary_color)
    for i, w in enumerate(line):
        t = escape_text(w["w"].upper() if style.uppercase else w["w"])
        if current is None or style.animation == "none":
            parts.append(t)
        elif style.animation == "karaoke":
            parts.append(f"{{\\c{hl}}}{t}{{\\c{base}}}" if i <= current else t)
        elif i == current:
            pop = "\\fscx118\\fscy118\\t(0,120,\\fscx100\\fscy100)" if style.animation == "pop" else ""
            parts.append(f"{{\\c{hl}{pop}}}{t}{{\\c{base}\\fscx100\\fscy100}}")
        else:
            parts.append(t)
    return " ".join(parts)


def caption_spans(words: list[dict], words_per_line: int, animation: str, duration: float) -> list[dict]:
    """Estrutura das legendas (compartilhada com o preview do editor — ver tests/fixtures/captions_cases.json).

    Cada span: {"s", "e", "line": [textos], "current": índice da palavra atual | None}.
    """
    lines = group_lines(words, max(1, words_per_line))
    spans: list[dict] = []
    for li, line in enumerate(lines):
        nxt = lines[li + 1][0]["s"] if li + 1 < len(lines) else None
        last_e = line[-1]["e"]
        line_end = nxt if nxt is not None and nxt - last_e <= HOLD_GAP_S else last_e + HOLD_AFTER_S
        if nxt is not None:
            line_end = min(line_end, nxt)
        line_end = round(min(line_end, duration), 3)
        line_start = line[0]["s"]
        if line_end <= line_start:
            continue
        texts = [w["w"] for w in line]
        if animation == "none":
            spans.append({"s": line_start, "e": line_end, "line": texts, "current": None})
            continue
        for wi, w in enumerate(line):
            s = line_start if wi == 0 else w["s"]
            e = line[wi + 1]["s"] if wi + 1 < len(line) else line_end
            if e > s:
                spans.append({"s": s, "e": e, "line": texts, "current": wi})
    return spans


def build_events(words: list[dict], style: Style, duration: float) -> list[tuple[float, float, str]]:
    """(início, fim, texto ASS) relativos ao corte."""
    out = []
    for sp in caption_spans(words, style.words_per_line, style.animation, duration):
        line = [{"w": t} for t in sp["line"]]
        out.append((sp["s"], sp["e"], _line_text(line, style, sp["current"])))
    return out


def build_ass(words: list[dict], style: Style, duration: float, title: str = "", title_until: float | None = None) -> str:
    y = round(max(0.05, min(0.95, style.position_y)) * PLAY_H)
    border_style = 1
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{style.font},{style.font_size},{ass_color(style.primary_color)},{ass_color(style.highlight_color)},{ass_color(style.outline_color)},{ass_color("#000000", 0x80)},0,0,0,0,100,100,0,0,{border_style},{style.outline_px},{style.shadow_px},5,40,40,0,1
Style: Title,Montserrat ExtraBold,64,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,3,18,0,8,60,60,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for s, e, text in build_events(words, style, duration):
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Caption,,0,0,0,,{{\\an5\\pos({PLAY_W // 2},{y})}}{text}")
    if title.strip():
        end = duration if title_until is None else min(duration, title_until)
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(end)},Title,,0,0,0,,{escape_text(title.strip())}")
    return header + "\n".join(lines) + "\n"
