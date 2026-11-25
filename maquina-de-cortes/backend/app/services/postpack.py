"""Pacote para postar (roadmap #9): textos por plataforma (IA local), capa automática e exportação em .zip.

- Textos: o Ollama recebe a fala do corte e devolve legenda + hashtags para TikTok, Reels e Shorts
  (título + descrição). Tudo normalizado aqui (limites de tamanho, hashtags sem acento/espaço, sem repetidas).
- Capa: candidatos espalhados pelo corte, pontuados por rosto (faces.json: tamanho, confiança, de frente,
  boca não escancarada) e nitidez (variância do Laplaciano) no quadro já enquadrado em 9:16.
- Exportar: MP4s + capas + textos.csv (abre no Excel/Planilhas) + textos.txt (para copiar e colar).
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PLATFORMS = ("tiktok", "reels", "shorts")
PLATFORM_LABELS = {"tiktok": "TikTok", "reels": "Instagram Reels", "shorts": "YouTube Shorts"}
MAX_TAGS = {"tiktok": 5, "reels": 8, "shorts": 3}
CAPTION_MAX = {"tiktok": 300, "reels": 600}
SHORTS_TITLE_MAX = 100  # limite do YouTube
SHORTS_DESC_MAX = 1000
TRANSCRIPT_MAX_CHARS = 4000

LANG_NAMES = {"pt": "português do Brasil", "en": "inglês", "es": "espanhol", "fr": "francês", "it": "italiano",
              "de": "alemão", "ja": "japonês"}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "tiktok": {"type": "object", "properties": {"legenda": {"type": "string"},
                                                    "hashtags": {"type": "array", "items": {"type": "string"}}},
                   "required": ["legenda", "hashtags"]},
        "reels": {"type": "object", "properties": {"legenda": {"type": "string"},
                                                   "hashtags": {"type": "array", "items": {"type": "string"}}},
                  "required": ["legenda", "hashtags"]},
        "shorts": {"type": "object", "properties": {"titulo": {"type": "string"}, "descricao": {"type": "string"},
                                                    "hashtags": {"type": "array", "items": {"type": "string"}}},
                   "required": ["titulo", "descricao", "hashtags"]},
    },
    "required": ["tiktok", "reels", "shorts"],
}

SYSTEM_PROMPT = """Você é social media de criadores de conteúdo e escreve os textos de publicação de cortes \
verticais curtos. Escreva em {lang}. Responda só com o JSON pedido.

Regras por plataforma:
- tiktok.legenda: 1 ou 2 frases curtas (até 150 caracteres) que despertem curiosidade sobre o corte, sem \
entregar o final. Pode usar no máximo 1 emoji. Sem hashtags dentro da legenda.
- tiktok.hashtags: 3 a 5 hashtags, misturando o assunto específico e 1 ou 2 amplas do nicho.
- reels.legenda: 2 a 4 frases (até 400 caracteres): gancho na primeira linha, contexto curto e uma chamada \
para comentar ou salvar. Sem hashtags dentro da legenda.
- reels.hashtags: 5 a 8 hashtags relevantes.
- shorts.titulo: título forte de até 70 caracteres, sem hashtags e sem aspas.
- shorts.descricao: 1 ou 2 frases explicando do que o corte trata.
- shorts.hashtags: 2 ou 3 hashtags (não inclua #shorts, ela é adicionada depois).

Nunca repita o título interno nem a frase de abertura palavra por palavra: escreva um texto novo, específico \
sobre o que acontece no corte (quem, o quê, por que é interessante). Nada de reticências vazias como "A reação…".
Nunca invente fatos que não estão na fala. Não use clickbait mentiroso.
Hashtags: sem o símbolo #, sem espaços, palavras reais que as pessoas pesquisam (ex.: gta6, podcast, humor), \
nada de palavras inventadas ou coladas sem sentido."""


def build_post_messages(title: str, hook: str, text: str, language: str, duration_s: float,
                        project_name: str = "") -> list[dict]:
    lang = LANG_NAMES.get((language or "pt").split("-")[0], language or "português do Brasil")
    if len(text) > TRANSCRIPT_MAX_CHARS:
        text = text[:TRANSCRIPT_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    user = (f"Vídeo original: {project_name}\n" if project_name else "") + (
        f"Título interno do corte: {title}\n"
        f"Frase de abertura: {hook}\n"
        f"Duração: {duration_s:.0f} s\n\n"
        f"Fala do corte:\n\"\"\"\n{text}\n\"\"\"")
    return [{"role": "system", "content": SYSTEM_PROMPT.format(lang=lang)}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Normalização dos textos
# ---------------------------------------------------------------------------
def clean_hashtag(tag: str) -> str:
    """'#Saúde Mental!' → 'SaudeMental'. Palavras viram CamelCase só se vierem separadas por espaço."""
    t = unicodedata.normalize("NFKD", str(tag)).encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^A-Za-z0-9_]+", t) if p]
    if len(parts) > 1:
        parts = [parts[0]] + [p[:1].upper() + p[1:] for p in parts[1:]]
    return "".join(parts)[:40]


def clean_hashtags(tags, limit: int, exclude: set[str] | None = None) -> list[str]:
    seen = {e.lower() for e in exclude or set()}
    out = []
    raw = tags if isinstance(tags, list) else re.split(r"[\s,]+", str(tags or ""))
    for t in raw:
        c = clean_hashtag(t)
        if len(c) < 2 or c.isdigit() or c.lower() in seen:
            continue
        seen.add(c.lower())
        out.append(c)
        if len(out) >= limit:
            break
    return out


def _clip_text(s, limit: int) -> str:
    s = re.sub(r"[ \t]+", " ", str(s or "")).strip()
    s = re.sub(r"\s*(\.\.\.|…)$", "", s) if len(s) < 40 else s  # "A reação do pai..." → sem reticências soltas
    s = re.sub(r"(^|\s)#\w+", "", s).strip()  # hashtags vão no campo próprio
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in (". ", "! ", "? ", "\n"):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            return cut[:i + 1].strip()
    cut = s[:limit - 1]  # espaço para o "…"
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(",;:") + "…"


def normalize_post(data: dict) -> dict:
    """Saída do LLM (ou edição do usuário) → formato salvo em Clip.post_json."""
    if not isinstance(data, dict):
        raise ValueError("JSON não é um objeto")
    tk, rl, sh = (data.get(k) if isinstance(data.get(k), dict) else {} for k in PLATFORMS)
    out = {
        "tiktok": {"caption": _clip_text(tk.get("legenda", tk.get("caption")), CAPTION_MAX["tiktok"]),
                   "hashtags": clean_hashtags(tk.get("hashtags"), MAX_TAGS["tiktok"])},
        "reels": {"caption": _clip_text(rl.get("legenda", rl.get("caption")), CAPTION_MAX["reels"]),
                  "hashtags": clean_hashtags(rl.get("hashtags"), MAX_TAGS["reels"])},
        "shorts": {"title": _clip_text(sh.get("titulo", sh.get("title")), SHORTS_TITLE_MAX).strip("\"'“”"),
                   "description": _clip_text(sh.get("descricao", sh.get("description")), SHORTS_DESC_MAX),
                   "hashtags": clean_hashtags(sh.get("hashtags"), MAX_TAGS["shorts"], exclude={"shorts"})},
    }
    if not (out["tiktok"]["caption"] or out["reels"]["caption"] or out["shorts"]["title"]):
        raise ValueError("JSON sem textos")
    return out


def parse_post(raw: str) -> dict:
    return normalize_post(json.loads(raw))


def load_post(raw: str) -> dict:
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def has_texts(post: dict) -> bool:
    return any(isinstance(post.get(k), dict) for k in PLATFORMS)


def tags_line(tags: list[str], extra: list[str] | None = None) -> str:
    return " ".join(f"#{t}" for t in [*tags, *(extra or [])])


def platform_text(post: dict, platform: str) -> str:
    """Texto pronto para colar na plataforma (legenda/descrição + hashtags)."""
    p = post.get(platform) or {}
    if platform == "shorts":
        return "\n\n".join(x for x in (p.get("description", ""), tags_line(p.get("hashtags", []), ["Shorts"])) if x)
    return "\n\n".join(x for x in (p.get("caption", ""), tags_line(p.get("hashtags", []))) if x)


# ---------------------------------------------------------------------------
# Capa
# ---------------------------------------------------------------------------
COVER_CANDIDATES = 8
COVER_EDGE_S = 0.4  # evita o primeiro/último instante (transições, fade)
CUT_GUARD_S = 0.35  # e quadros colados numa troca de cena (borrão de transição)


def face_quality(faces_at: list[list[float]], window: tuple[float, float] | None = None) -> float:
    """Nota do melhor rosto da amostra: tamanho × confiança × frontalidade, penalizando boca muito aberta.
    `window`: faixa X normalizada visível no crop (rostos fora dela não aparecem na capa)."""
    best = 0.0
    for f in faces_at or []:
        cx, h, score = f[0], f[3], f[4]
        if window and not (window[0] <= cx <= window[1]):
            continue
        frontal = min(1.0, (f[6] if len(f) > 6 else 0.4) / 0.35)
        mar = f[7] if len(f) > 7 else -1
        mouth = 0.6 if mar > 0.06 else 1.0
        best = max(best, min(h, 0.6) * score * frontal * mouth)
    return best


def sharpness(img: np.ndarray) -> float:
    import cv2

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if g.shape[1] > 540:
        g = cv2.resize(g, (540, int(g.shape[0] * 540 / g.shape[1])), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


@dataclass
class Candidate:
    t: float  # absoluto (s na fonte)
    face: float
    sharp: float = 0.0
    total: float = 0.0


def cover_candidates(faces: dict, cuts: list[float], start: float, end: float, n: int = COVER_CANDIDATES,
                     window_at=None) -> list[Candidate]:
    """Divide o corte em `n` faixas e pega o melhor instante (por rosto) de cada uma.
    `window_at(t)` → faixa X visível no crop naquele instante (ou None)."""
    ffps = faces.get("fps", 5) if faces else 5
    frames = faces.get("frames", []) if faces else []
    a, b = start + COVER_EDGE_S, end - COVER_EDGE_S
    if b <= a:
        a, b = start, max(start, end - 0.05)
    edges = np.linspace(a, b, n + 1)
    out: list[Candidate] = []
    for lo, hi in zip(edges, edges[1:]):
        ts = [t for t in np.arange(np.ceil(lo * ffps) / ffps, hi, 1 / ffps)
              if not any(abs(t - c) < CUT_GUARD_S for c in cuts)] or [float((lo + hi) / 2)]
        best = None
        for t in ts:
            i = int(round(t * ffps))
            q = face_quality(frames[i] if i < len(frames) else [], window_at(t) if window_at else None)
            if best is None or q > best.face:
                best = Candidate(t=round(float(t), 3), face=q)
        out.append(best)  # type: ignore[arg-type]
    return out


def pick_cover(cands: list[Candidate]) -> Candidate:
    """Combina rosto (65%) e nitidez (35%), cada um relativo ao melhor candidato."""
    fmax = max((c.face for c in cands), default=0) or 0
    smax = max((c.sharp for c in cands), default=0) or 1
    for c in cands:
        c.total = (0.65 * c.face / fmax if fmax > 0 else 0) + (0.35 if fmax > 0 else 1.0) * c.sharp / smax
    return max(cands, key=lambda c: c.total)


def cover_ass(title: str, font: str = "Montserrat ExtraBold") -> str:
    """Título grande no terço de baixo (fora da área do ícone de perfil/descrição das plataformas)."""
    from .captions import escape_text

    text = escape_text(title.strip().upper())
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cover,{font},120,&H00FFFFFF,&H0000E6FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,9,4,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,Cover,,0,0,0,,{{\\an5\\pos(540,1240)}}{text}
"""


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
CSV_COLUMNS = ["arquivo", "capa", "nota", "duracao_s", "tiktok_legenda", "tiktok_hashtags", "reels_legenda",
               "reels_hashtags", "shorts_titulo", "shorts_descricao", "shorts_hashtags"]


@dataclass
class ExportItem:
    mp4: Path
    name: str  # nome do MP4 no zip
    score: float
    duration_s: float
    title: str
    post: dict
    cover: Path | None = None
    cover_title: Path | None = None


def _cover_names(item: ExportItem) -> tuple[str, str]:
    stem = Path(item.name).stem
    return f"capas/{stem}.jpg", f"capas/{stem}-com-titulo.jpg"


def csv_text(items: list[ExportItem]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for it in items:
        p = it.post
        tk, rl, sh = (p.get(k) or {} for k in PLATFORMS)
        w.writerow([it.name, _cover_names(it)[0] if it.cover else "", round(it.score), round(it.duration_s, 1),
                    tk.get("caption", ""), tags_line(tk.get("hashtags", [])),
                    rl.get("caption", ""), tags_line(rl.get("hashtags", [])),
                    sh.get("title", "") or it.title, sh.get("description", ""),
                    tags_line(sh.get("hashtags", []), ["Shorts"]) if sh else ""])
    return "﻿" + buf.getvalue()  # BOM: o Excel abre em UTF-8


def txt_text(items: list[ExportItem], project_name: str, skipped: int = 0) -> str:
    out = [f"Pacote para postar — {project_name}", f"{len(items)} corte(s)"
           + (f" · {skipped} sem MP4 ficaram de fora" if skipped else ""), ""]
    for it in items:
        out += ["=" * 60, f"{it.name}  (nota {round(it.score)} · {it.duration_s:.0f} s)", "=" * 60]
        if not has_texts(it.post):
            out += ["(textos ainda não gerados — use “Gerar textos” no app)", ""]
            continue
        sh = it.post.get("shorts") or {}
        for k in PLATFORMS:
            out.append(f"--- {PLATFORM_LABELS[k]} ---")
            if k == "shorts":
                out.append(f"Título: {sh.get('title', '') or it.title}")
            out += [platform_text(it.post, k), ""]
    return "\n".join(out) + "\n"


def build_zip(dest: Path, items: list[ExportItem], project_name: str, skipped: int = 0) -> Path:
    """MP4 e JPG já são comprimidos: vão sem compressão (rápido); só os textos usam deflate."""
    tmp = dest.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for it in items:
            z.write(it.mp4, it.name)
            cn, ctn = _cover_names(it)
            if it.cover and it.cover.is_file():
                z.write(it.cover, cn)
            if it.cover_title and it.cover_title.is_file():
                z.write(it.cover_title, ctn)
        z.writestr("textos.csv", csv_text(items), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("textos.txt", txt_text(items, project_name, skipped), compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(dest)
    return dest
