"""Reenquadramento 9:16 (seção 8.5).

1. Pré-análise por projeto (uma vez): cenas (PySceneDetect) → scenes.json; rostos a 5 fps (YuNet) → faces.json.
2. Por corte: trilha de crop por frame — alvo = rosto dominante da cena, zona morta + suavização exponencial,
   salto seco na troca de cena. Modos: auto, split (2 rostos em cima/embaixo), manual (keyframes).
3. Render: ffmpeg decodifica a fonte → Python recorta cada frame → ffmpeg codifica (com legenda e áudio).
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "assets" / "models"
YUNET_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
FACE_FPS = 5
DETECT_W, DETECT_H = 960, 540
FACE_MIN_SCORE = 0.6
FACE_MIN_SIZE = 0.035  # rostos menores que 3,5% da altura (plateia, fundo) são ignorados
DEADZONE = 0.08  # fração da largura do crop
ALPHA = 0.2  # suavização exponencial por amostra (5 fps → constante de tempo ~1 s)
CLUSTER_DX = 0.08  # mesma pessoa se o centro X variar menos que isso (normalizado)
SPLIT_MIN_RATIO = 0.6  # cena vira "split" se ≥ 60% das amostras tiverem os 2 rostos
FACES_VERSION = 5  # v2: atividade da boca; v3/v4: desconta movimento em volta e perfil; v5: abertura dos lábios
LANDMARKER_MODEL = MODELS_DIR / "face_landmarker.task"
MAR_MIN_FACE_H = 0.08  # rostos menores que isso: lábios ilegíveis, nem tenta
MAR_QUIET, MAR_TALK = 0.02, 0.05  # desvio da abertura dos lábios em ~1 s: calado ≤ 0,02, falando ≥ 0,05
SPEAKER_SWITCH_SAMPLES = 4  # outra pessoa precisa falar mais por 4 amostras (0,8 s) seguidas…
SPEAKER_MIN_HOLD_S = 1.5  # …e ninguém troca antes de 1,5 s no enquadramento
SPEAKER_MARGIN = 1.3  # a atividade nova precisa ser 30% maior que a atual
GAMEPLAY_TOP_RATIO = 0.32  # webcam ocupa ~1/3 de cima, jogo ~2/3
OUT_W, OUT_H = 1080, 1920


class ReframeCanceled(Exception):
    pass


class ReframeError(Exception):
    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


# ---------------------------------------------------------------------------
# 1. Pré-análise
# ---------------------------------------------------------------------------
def detect_scenes(video: Path, on_progress: Callable[[float], None], is_canceled: Callable[[], bool],
                  threshold: float = 27.0) -> list[float]:
    """Tempos (s) das trocas de cena. Processa em blocos de 60 s para reportar progresso e permitir cancelar."""
    from scenedetect import ContentDetector, SceneManager, open_video

    v = open_video(str(video))
    total = v.duration.get_seconds() if v.duration else 0
    sm = SceneManager()
    sm.auto_downscale = True
    sm.add_detector(ContentDetector(threshold=threshold, min_scene_len=8))
    pos = 0.0
    while True:
        if is_canceled():
            raise ReframeCanceled()
        pos += 60
        n = sm.detect_scenes(v, end_time=pos)
        on_progress(min(100.0, 100 * pos / total) if total else 50)
        if n == 0 or (total and pos >= total):
            break
    scenes = sm.get_scene_list(start_in_scene=True)
    return [round(s[0].get_seconds(), 3) for s in scenes[1:]]


def _detector():
    import cv2

    if not YUNET_MODEL.exists():
        raise ReframeError("Modelo de detecção de rosto não encontrado.", str(YUNET_MODEL))
    return cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (DETECT_W, DETECT_H), FACE_MIN_SCORE, 0.3, 50)


def letterbox(aspect: float) -> tuple[float, float, float, float]:
    """(ox, oy, w, h) da imagem dentro do quadro de detecção 960×540 (com bordas se não for 16:9)."""
    if aspect >= DETECT_W / DETECT_H:
        w, h = DETECT_W, DETECT_W / aspect
    else:
        w, h = DETECT_H * aspect, DETECT_H
    return (DETECT_W - w) / 2, (DETECT_H - h) / 2, w, h


def _norm_patch(gray: np.ndarray, cx: float, cy: float, w: float, h: float) -> np.ndarray | None:
    """Recorte normalizado (24×16, média 0) para comparar a mesma região entre quadros."""
    import cv2

    H, W = gray.shape
    x0, x1 = int(max(0, cx - w / 2)), int(min(W, cx + w / 2))
    y0, y1 = int(max(0, cy - h / 2)), int(min(H, cy + h / 2))
    if x1 - x0 < 6 or y1 - y0 < 4:
        return None
    p = cv2.resize(gray[y0:y1, x0:x1], (24, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    return (p - p.mean()) / (p.std() + 8.0)


def mouth_activity(prev: list[dict], cur: list[dict]) -> None:
    """Para cada rosto atual, mede quanto a boca mudou desde o quadro anterior, descontando o movimento
    da cabeça (medido nos olhos). Preenche cur[i]["act"] (−1 = sem referência no quadro anterior)."""
    for f in cur:
        f["act"] = -1.0
        best = min(prev, key=lambda p: (p["cx"] - f["cx"]) ** 2 + (p["cy"] - f["cy"]) ** 2, default=None)
        if best is None or abs(best["cx"] - f["cx"]) > 0.5 * f["w"] or abs(best["cy"] - f["cy"]) > 0.5 * f["h"]:
            continue
        if f["mouth"] is None or best["mouth"] is None:
            continue
        dm = float(np.abs(f["mouth"] - best["mouth"]).mean())
        de = float(np.abs(f["eyes"] - best["eyes"]).mean()) if f["eyes"] is not None and best["eyes"] is not None else 0.0
        # região maior em volta da boca: se ela muda tanto quanto a boca, é mão/cabeça passando, não fala.
        # (a boca é ~35% dessa região, então fala de verdade muda a região grande bem menos que a boca)
        dr = float(np.abs(f["ring"] - best["ring"]).mean()) if f["ring"] is not None and best["ring"] is not None else 0.0
        f["act"] = max(0.0, dm - 0.8 * max(de, dr))


class LipReader:
    """Abertura dos lábios (altura interna ÷ largura da boca) com o FaceLandmarker do MediaPipe.
    Funciona em rostos de frente/três-quartos; de perfil costuma falhar (→ None)."""

    def __init__(self) -> None:
        self.lm = None
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision

            if LANDMARKER_MODEL.exists():
                self.mp = mp
                self.lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(LANDMARKER_MODEL)), num_faces=1))
        except Exception:  # noqa: BLE001 — sem MediaPipe: segue só com a atividade da boca
            log.warning("FaceLandmarker indisponível; detecção de quem fala fica menos precisa")

    def mar(self, rgb: np.ndarray, cx: float, cy: float, w: float, h: float) -> float | None:
        if self.lm is None:
            return None
        s = max(w, h) * 1.6
        H, W = rgb.shape[:2]
        crop = np.ascontiguousarray(rgb[int(max(0, cy - s / 2)):int(min(H, cy + s / 2)),
                                        int(max(0, cx - s / 2)):int(min(W, cx + s / 2))])
        if crop.shape[0] < 24 or crop.shape[1] < 24:
            return None
        r = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=crop))
        if not r.face_landmarks:
            return None
        p = r.face_landmarks[0]
        width = float(np.hypot(p[78].x - p[308].x, p[78].y - p[308].y))
        return float(np.hypot(p[13].x - p[14].x, p[13].y - p[14].y)) / max(width, 1e-6)


def detect_faces(video: Path, duration: float, on_progress: Callable[[float], None],
                 is_canceled: Callable[[], bool], register_process: Callable | None = None,
                 aspect: float = 16 / 9) -> dict:
    """Rostos a 5 fps, em coordenadas normalizadas do quadro original:
    [cx, cy, w, h, score, atividade_da_boca, frontalidade, abertura_dos_lábios (−1 = ilegível)]. Frames decodificados pelo ffmpeg (tempo exato = i / FACE_FPS)."""
    import cv2

    det = _detector()
    lips = LipReader()
    ox, oy, iw, ih = letterbox(aspect)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an",
           "-vf", f"fps={FACE_FPS},scale={DETECT_W}:{DETECT_H}:force_original_aspect_ratio=decrease,"
                  f"pad={DETECT_W}:{DETECT_H}:(ow-iw)/2:(oh-ih)/2",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if register_process:
        register_process(p)
    frame_bytes = DETECT_W * DETECT_H * 3
    expected = max(1, int(duration * FACE_FPS))
    frames: list[list[list[float]]] = []
    buf = bytearray(frame_bytes)
    prev: list[dict] = []
    try:
        assert p.stdout
        while True:
            if is_canceled():
                raise ReframeCanceled()
            n = p.stdout.readinto(buf)
            if not n or n < frame_bytes:
                break
            img = np.frombuffer(buf, np.uint8).reshape(DETECT_H, DETECT_W, 3)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            rgb = None
            _, dets = det.detect(img)
            cur: list[dict] = []
            for d in dets if dets is not None else []:
                x, y, w, h, score = float(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[-1])
                if h / ih < FACE_MIN_SIZE:
                    continue
                (rex, rey), (lex, ley) = d[4:6], d[6:8]
                (rmx, rmy), (lmx, lmy) = d[10:12], d[12:14]
                mw = max(4.0, float(np.hypot(lmx - rmx, lmy - rmy)))
                ed = max(4.0, float(np.hypot(lex - rex, ley - rey)))
                cur.append({
                    "cx": x + w / 2, "cy": y + h / 2, "w": w, "h": h, "score": score,
                    # boca + queixo (o queixo desce quando a pessoa fala)
                    "mouth": _norm_patch(gray, (rmx + lmx) / 2, (rmy + lmy) / 2 + 0.25 * mw, 1.8 * mw, 1.4 * mw),
                    "eyes": _norm_patch(gray, (rex + lex) / 2, (rey + ley) / 2, 1.6 * ed, 0.8 * ed),
                    "ring": _norm_patch(gray, (rmx + lmx) / 2, (rmy + lmy) / 2 + 0.25 * mw, 3.0 * mw, 2.4 * mw),
                    "frontal": ed / max(w, 1.0),  # ~0,4 de frente, ~0,15–0,25 de perfil
                    "mar": None,
                })
                if h / ih >= MAR_MIN_FACE_H and lips.lm is not None:
                    if rgb is None:
                        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    cur[-1]["mar"] = lips.mar(rgb, x + w / 2, y + h / 2, w, h)
            mouth_activity(prev, cur)
            prev = cur
            frames.append([[round((f["cx"] - ox) / iw, 4), round((f["cy"] - oy) / ih, 4), round(f["w"] / iw, 4),
                            round(f["h"] / ih, 4), round(f["score"], 3), round(f["act"], 3), round(f["frontal"], 3),
                            round(f["mar"], 4) if f["mar"] is not None else -1]
                           for f in cur])
            if len(frames) % 25 == 0:
                on_progress(min(99.0, 100 * len(frames) / expected))
    finally:
        if p.poll() is None:
            p.terminate()
        p.wait()
    return {"version": FACES_VERSION, "fps": FACE_FPS, "frames": frames}


def analyze_project(proxy: Path, duration: float, out_dir: Path, report: Callable[[float, str], None],
                    is_canceled: Callable[[], bool], register_process: Callable | None = None,
                    aspect: float = 16 / 9) -> tuple[dict, list[float]]:
    """Gera (ou reaproveita) scenes.json e faces.json do projeto."""
    scenes_p, faces_p = out_dir / "scenes.json", out_dir / "faces.json"
    if scenes_p.exists():
        cuts = json.loads(scenes_p.read_text())["cuts"]
    else:
        report(0, "Detectando trocas de câmera…")
        cuts = detect_scenes(proxy, lambda pct: report(0.3 * pct, "Detectando trocas de câmera…"), is_canceled)
        _atomic_write(scenes_p, {"cuts": cuts})
    faces = json.loads(faces_p.read_text()) if faces_p.exists() else None
    if faces is None or faces.get("version", 1) < FACES_VERSION:  # análise antiga sem atividade da boca: refaz
        faces = detect_faces(proxy, duration, lambda pct: report(30 + 0.7 * pct, "Procurando rostos e quem fala…"),
                             is_canceled, register_process, aspect)
        _atomic_write(faces_p, faces)
    return faces, cuts


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# 2. Trilha de crop
# ---------------------------------------------------------------------------
@dataclass
class Cluster:
    cx: float
    cy: float
    weight: float = 0.0  # soma das áreas (maior + mais frequente = dominante)
    count: int = 0

    def add(self, f: list[float]) -> None:
        self.cx = (self.cx * self.count + f[0]) / (self.count + 1)
        self.cy = (self.cy * self.count + f[1]) / (self.count + 1)
        self.count += 1
        self.weight += f[2] * f[3]


def cluster_faces(samples: list[list[list[float]]]) -> list[Cluster]:
    """Agrupa rostos da cena por posição X (pessoas sentadas mudam pouco de lugar)."""
    clusters: list[Cluster] = []
    for faces in samples:
        for f in faces:
            best = min(clusters, key=lambda c: abs(c.cx - f[0]), default=None)
            if best is not None and abs(best.cx - f[0]) <= CLUSTER_DX:
                best.add(f)
            else:
                c = Cluster(f[0], f[1])
                c.add(f)
                clusters.append(c)
    return sorted(clusters, key=lambda c: c.weight, reverse=True)


def _face_in(cluster: Cluster, faces: list[list[float]]) -> list[float] | None:
    cands = [f for f in faces if abs(f[0] - cluster.cx) <= CLUSTER_DX * 1.5]
    return max(cands, key=lambda f: f[2] * f[3]) if cands else None


def smooth(targets: list[float | None], deadzone: float, alpha: float = ALPHA, default: float = 0.5) -> list[float]:
    """Zona morta + suavização exponencial. Amostras sem alvo mantêm a posição. Começa no 1º alvo (sem rampa)."""
    known = [t for t in targets if t is not None]
    if not known:
        return [default] * len(targets)
    head = [t for t in targets[:FACE_FPS] if t is not None]
    pos = goal = float(np.median(head)) if head else known[0]
    out = []
    for t in targets:
        if t is not None and abs(t - goal) > deadzone:
            goal = t
        pos += alpha * (goal - pos)
        out.append(pos)
    return out


@dataclass
class Track:
    """Trilha por frame do corte (tempos relativos ao início do corte)."""

    mode: str
    fps: float
    src_w: int
    src_h: int
    n: int
    crop_w: int  # largura do crop 9:16 em px da fonte (altura = src_h)
    layout: list[int] = field(default_factory=list)  # 0 = um crop, 1 = split, 2 = gameplay (caixas fixas)
    cx: list[float] = field(default_factory=list)  # centro X normalizado (layout 0)
    split: list[list[float] | None] = field(default_factory=list)  # [ax, ay, bx, by] normalizados (layout 1)
    cuts: list[float] = field(default_factory=list)  # trocas de cena dentro do corte (s, relativos)
    switches: list[float] = field(default_factory=list)  # trocas de quem fala (modo speaker; s, relativos)
    gameplay: dict | None = None  # {"cam": [x,y,w,h] | None, "game": [x,y,w,h], "top_ratio"} normalizados

    def to_json(self) -> dict:
        return {"mode": self.mode, "fps": self.fps, "src_w": self.src_w, "src_h": self.src_h, "frames": self.n,
                "crop_w": self.crop_w, "crop_w_norm": round(self.crop_w / self.src_w, 4), "cuts": self.cuts,
                "switches": self.switches, "layout": self.layout, "cx": [round(x, 4) for x in self.cx],
                "split": [[round(v, 4) for v in s] if s else None for s in self.split], "gameplay": self.gameplay}


def crop_width(src_w: int, src_h: int) -> int:
    return min(src_w, int(src_h * 9 / 16) // 2 * 2)


def _interp(sample_t: np.ndarray, values: list[float], frame_t: np.ndarray) -> np.ndarray:
    if len(values) == 1:
        return np.full(len(frame_t), values[0])
    return np.interp(frame_t, sample_t, np.array(values))


# --- gameplay: webcam em cima, jogo embaixo ------------------------------------------
def detect_webcam(faces: dict) -> list[float] | None:
    """Rosto da facecam = rosto que fica parado no mesmo lugar em boa parte do vídeo (o overlay não se mexe).
    Devolve [cx, cy, w, h] mediano (normalizado) ou None."""
    frames = faces.get("frames", [])
    if not frames:
        return None
    groups: list[list[list[float]]] = []
    for fs in frames:
        for f in fs:
            g = next((g for g in groups if abs(g[0][0] - f[0]) < 0.04 and abs(g[0][1] - f[1]) < 0.05), None)
            if g is None:
                groups.append([f])
            else:
                g.append(f)
    best = None
    for g in groups:
        arr = np.array([f[:4] for f in g])
        presence = len(g) / len(frames)
        if presence < 0.25 or np.median(arr[:, 3]) > 0.45:  # pouca presença ou rosto grande demais (é a câmera principal)
            continue
        if arr[:, 0].std() > 0.03 or arr[:, 1].std() > 0.04:  # se mexe muito: não é um overlay fixo
            continue
        if best is None or len(g) > len(best):
            best = g
    if best is None:
        return None
    return [round(float(v), 4) for v in np.median(np.array([f[:4] for f in best]), axis=0)]


def _clamp_box(x: float, y: float, w: float, h: float) -> list[float]:
    w, h = min(w, 1.0), min(h, 1.0)
    return [round(min(max(x, 0.0), 1 - w), 4), round(min(max(y, 0.0), 1 - h), 4), round(w, 4), round(h, 4)]


def gameplay_boxes(src_w: int, src_h: int, cam_face: list[float] | None, layout: dict | None = None) -> dict:
    """Caixas (normalizadas) da webcam e do jogo. `layout` (do editor) pode trazer:
    top_ratio, cam_center [x, y], cam_w (largura normalizada da webcam) e game_cx."""
    layout = layout or {}
    r = float(min(0.6, max(0.25, layout.get("top_ratio", GAMEPLAY_TOP_RATIO))))
    top_h = int(round(r * OUT_H)) // 2 * 2
    bot_h = OUT_H - top_h
    top_aspect = OUT_W / top_h  # largura/altura em pixels
    bot_aspect = OUT_W / bot_h

    cam = None
    center = layout.get("cam_center")
    if center is None and cam_face:
        # webcam: rosto ocupando ~metade da altura do painel, um pouco acima do meio
        fh_px = cam_face[3] * src_h
        ch_px = fh_px * 1.8  # justo o bastante para não pegar a borda do overlay
        cw_px = ch_px * top_aspect
        center = [cam_face[0], cam_face[1] + 0.05 * ch_px / src_h]
        cam_w = cw_px / src_w
    else:
        cam_w = float(layout.get("cam_w", 0.3))
    if center is not None:
        cam_w = float(layout.get("cam_w", cam_w))
        cw_px = cam_w * src_w
        ch_px = cw_px / top_aspect
        if ch_px > src_h:  # mais alto que o quadro: limita pela altura
            ch_px = src_h
            cw_px = ch_px * top_aspect
        cam = _clamp_box(center[0] - cw_px / src_w / 2, center[1] - ch_px / src_h / 2, cw_px / src_w, ch_px / src_h)

    # jogo: crop centralizado com a proporção do painel de baixo
    gw_px = min(src_w, src_h * bot_aspect)
    gh_px = gw_px / bot_aspect
    gcx = float(layout.get("game_cx", 0.5))
    game = _clamp_box(gcx - gw_px / src_w / 2, 0.5 - gh_px / src_h / 2, gw_px / src_w, gh_px / src_h)
    return {"cam": cam, "game": game, "top_ratio": round(top_h / OUT_H, 4), "cam_detected": cam_face is not None,
            "cam_face": cam_face}


# --- quem está falando ----------------------------------------------------------------
def speech_mask(sample_t: np.ndarray, speech: list[tuple[float, float]] | None) -> np.ndarray:
    if speech is None:
        return np.ones(len(sample_t), dtype=bool)
    starts = np.array([a for a, _ in speech])
    ends = np.array([b for _, b in speech])
    out = np.zeros(len(sample_t), dtype=bool)
    for i, t in enumerate(sample_t):
        j = np.searchsorted(starts, t + 0.1) - 1
        out[i] = j >= 0 and ends[j] >= t - 0.1
    return out


def _rolling_nanstd(v: np.ndarray, win: int, min_valid: int = 3) -> np.ndarray:
    out = np.full(len(v), np.nan)
    h = win // 2
    for i in range(len(v)):
        w = v[max(0, i - h): i + h + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_valid:
            out[i] = float(w.std())
    return out


def speaking_scores(samples: list[list[list[float]]], clusters: list[Cluster],
                    voice: np.ndarray | None = None) -> np.ndarray:
    """Probabilidade (0–1) de cada pessoa estar falando, por amostra. −1 = fora do quadro.

    1º) abertura dos lábios (desvio em ~1 s): calado ≤ 0,02, falando ≥ 0,05 — sinal forte e bimodal;
    2º) exclusão: se só parte das pessoas tem lábios legíveis (as outras de perfil), quem é ilegível recebe
        o que "sobra" (há voz e quem é legível está calado → fala quem não dá para ler);
    3º) ninguém legível: atividade da boca por diff de imagem, normalizada por pessoa (último recurso).
    """
    k, n = len(clusters), len(samples)
    present = np.zeros((k, n), dtype=bool)
    mar = np.full((k, n), np.nan)
    act = np.zeros((k, n))
    for i, s in enumerate(samples):
        for ci, c in enumerate(clusters):
            f = _face_in(c, s)
            if f is None:
                continue
            present[ci, i] = True
            act[ci, i] = max(0.0, f[5]) if len(f) > 5 else 0.0
            if len(f) > 6:
                act[ci, i] *= float(np.clip((f[6] - 0.15) / 0.2, 0.25, 1.0))
            if len(f) > 7 and f[7] >= 0:
                mar[ci, i] = f[7]
    lip = np.array([_rolling_nanstd(mar[ci], FACE_FPS) for ci in range(k)])  # ~1 s
    lip_p = np.clip((lip - MAR_QUIET) / (MAR_TALK - MAR_QUIET), 0, 1)

    # último recurso: diff de imagem normalizado pelo "parado" de cada pessoa
    ev = np.zeros((k, n))
    for ci in range(k):
        vals = act[ci][present[ci]]
        if len(vals):
            base = float(np.percentile(vals, 25))
            spread = float(np.percentile(vals, 90)) - base
            ev[ci] = np.clip((act[ci] - base) / (spread + 0.05), 0, 1)
    if voice is not None and len(voice) == n and voice.max() > 0:
        ev = ev * (0.3 + 0.7 * (voice / voice.max()))
    kern = np.ones(FACE_FPS) / FACE_FPS
    ev = np.array([np.convolve(ev[ci], kern, mode="same") for ci in range(k)])

    out = np.full((k, n), -1.0)
    for i in range(n):
        on = np.flatnonzero(present[:, i])
        if not len(on):
            continue
        known = [ci for ci in on if not np.isnan(lip_p[ci, i])]
        unknown = [ci for ci in on if np.isnan(lip_p[ci, i])]
        if known:
            for ci in known:
                out[ci, i] = lip_p[ci, i]
            rest = 1.0 - max(lip_p[ci, i] for ci in known)
            for ci in unknown:
                out[ci, i] = rest / len(unknown)
        else:
            for ci in unknown:
                out[ci, i] = ev[ci, i]
    return out


def speaker_runs(samples: list[list[list[float]]], sample_t: np.ndarray, clusters: list[Cluster],
                 speaking: np.ndarray, voice: np.ndarray | None = None) -> list[tuple[int, int]]:
    """[(índice da amostra onde começa, índice do cluster)] — quem está falando, com histerese:
    troca só se a outra pessoa estiver claramente à frente por 0,8 s e ninguém ficou menos de 1,5 s."""
    n = len(samples)
    sm = speaking_scores(samples, clusters, voice)
    head = sm[:, : 2 * FACE_FPS].clip(min=0).sum(axis=1)
    cur = int(np.argmax(head)) if head.max() > 0 else 0
    runs = [(0, cur)]
    last_switch = sample_t[0] if n else 0.0
    cand, count = -1, 0
    for i in range(n):
        best = int(np.argmax(sm[:, i]))
        absent = sm[cur, i] < 0 and sm[best, i] >= 0  # quem estava no quadro sumiu
        wins = speaking[i] and best != cur and sm[best, i] >= max(sm[cur, i], 0.0) + 0.3
        if absent or wins:
            count = count + 1 if cand == best else 1
            cand = best
            j = i - count + 1  # a troca acontece onde a vantagem começou
            if count >= SPEAKER_SWITCH_SAMPLES and sample_t[j] - last_switch >= SPEAKER_MIN_HOLD_S:
                runs.append((j, best))
                cur, last_switch, cand, count = best, sample_t[j], -1, 0
        else:
            cand, count = -1, 0
    return runs


def compute_track(faces: dict, cuts: list[float], start: float, end: float, src_w: int, src_h: int,
                  fps: float, mode: str = "auto", keyframes: list[dict] | None = None,
                  speech: list[tuple[float, float]] | None = None, layout: dict | None = None,
                  voice: np.ndarray | None = None, voice_hop: float = 0.1) -> Track:
    """`voice`: energia do áudio (RMS) a cada `voice_hop` s — usada no modo speaker."""
    n = max(1, int(round((end - start) * fps)))
    cw = crop_width(src_w, src_h)
    cwn = cw / src_w
    half = cwn / 2
    tr = Track(mode=mode, fps=fps, src_w=src_w, src_h=src_h, n=n, crop_w=cw)
    frame_t = start + np.arange(n) / fps  # tempos absolutos de cada frame de saída

    if mode == "gameplay":
        tr.gameplay = gameplay_boxes(src_w, src_h, detect_webcam(faces), layout)
        tr.layout, tr.cx, tr.split = [2] * n, [0.5] * n, [None] * n
        return tr

    if mode == "manual" and keyframes:
        kf = sorted(keyframes, key=lambda k: k["t"])
        kt = np.array([k["t"] for k in kf]) + start
        kx = np.array([k["x"] for k in kf])
        # interpolação linear com easing (smoothstep) entre keyframes
        idx = np.clip(np.searchsorted(kt, frame_t) - 1, 0, max(0, len(kt) - 2))
        if len(kt) == 1:
            xs = np.full(n, kx[0])
        else:
            t0, t1 = kt[idx], kt[idx + 1]
            u = np.clip((frame_t - t0) / np.maximum(t1 - t0, 1e-6), 0, 1)
            u = u * u * (3 - 2 * u)
            xs = kx[idx] + (kx[idx + 1] - kx[idx]) * u
        tr.layout, tr.cx, tr.split = [0] * n, np.clip(xs, half, 1 - half).tolist(), [None] * n
        return tr

    if mode == "center" or cwn >= 0.999:
        tr.layout, tr.cx, tr.split = [0] * n, [0.5] * n, [None] * n
        return tr

    ffps = faces.get("fps", FACE_FPS)
    all_frames = faces.get("frames", [])
    inner_cuts = [c for c in cuts if start < c < end]
    tr.cuts = [round(c - start, 3) for c in inner_cuts]
    bounds = [start, *inner_cuts, end]
    layout_arr = np.zeros(n, dtype=int)
    cx = np.full(n, 0.5)
    split: list[list[float] | None] = [None] * n

    def follow(samples, sample_t, cluster, ft):
        targets = [(_face_in(cluster, s) or [None])[0] for s in samples]
        return _interp(sample_t, smooth(targets, DEADZONE * cwn, default=cluster.cx), ft)

    for a, b in zip(bounds, bounds[1:]):
        fmask = (frame_t >= a - 1e-6) & (frame_t < b - 1e-6)
        if b == end:
            fmask |= frame_t >= b - 1e-6
        if not fmask.any():
            continue
        i0, i1 = math.ceil(a * ffps), max(math.ceil(a * ffps) + 1, math.ceil(b * ffps))
        samples = [all_frames[i] if i < len(all_frames) else [] for i in range(i0, i1)]
        sample_t = np.array([i / ffps for i in range(i0, i1)])
        clusters = cluster_faces(samples)
        ft = frame_t[fmask]

        if mode == "split" and len(clusters) >= 2:
            a_c, b_c = sorted(clusters[:2], key=lambda c: c.cx)  # esquerda em cima
            both = sum(1 for s in samples if _face_in(a_c, s) and _face_in(b_c, s))
            if both / max(1, len(samples)) >= SPLIT_MIN_RATIO:
                tracks = []
                for c in (a_c, b_c):
                    fx = [(_face_in(c, s) or [None])[0] for s in samples]
                    fy = [(_face_in(c, s) or [None, None])[1] for s in samples]
                    tracks.append(_interp(sample_t, smooth(fx, DEADZONE * 0.5, default=c.cx), ft))
                    tracks.append(_interp(sample_t, smooth(fy, 0.05, default=c.cy), ft))
                layout_arr[fmask] = 1
                for k, idx in enumerate(np.flatnonzero(fmask)):
                    split[idx] = [float(tracks[0][k]), float(tracks[1][k]), float(tracks[2][k]), float(tracks[3][k])]
                continue

        if not clusters:
            cx[fmask] = 0.5  # cena sem rosto: centro
            continue

        if mode == "speaker":
            # só pessoas que aparecem de verdade na cena (descarta rostos de fundo/passagem)
            top = clusters[0].weight
            people = [c for c in clusters if c.weight >= 0.15 * top and c.count >= 0.2 * len(samples)][:3]
            if len(people) >= 2:
                v = None
                if voice is not None and len(voice):
                    idx_v = np.clip((sample_t / voice_hop).astype(int), 0, len(voice) - 1)
                    v = voice[idx_v]
                runs = speaker_runs(samples, sample_t, people, speech_mask(sample_t, speech), v)
                idxs = np.flatnonzero(fmask)
                for r, (j, ci) in enumerate(runs):
                    t_from = a if r == 0 else sample_t[j]
                    t_to = b if r + 1 == len(runs) else sample_t[runs[r + 1][0]]
                    sel = (ft >= t_from - 1e-6) & (ft < t_to - 1e-6) if r + 1 < len(runs) else ft >= t_from - 1e-6
                    if not sel.any():
                        continue
                    j_end = runs[r + 1][0] if r + 1 < len(runs) else len(samples)
                    cx[idxs[sel]] = follow(samples[j:j_end], sample_t[j:j_end], people[ci], ft[sel])
                    if r > 0:
                        tr.switches.append(round(float(t_from - start), 3))
                continue

        cx[fmask] = follow(samples, sample_t, clusters[0], ft)

    tr.layout = layout_arr.tolist()
    tr.cx = np.clip(cx, half, 1 - half).tolist()
    tr.split = split
    return tr


# ---------------------------------------------------------------------------
# 3. Render com crop variável
# ---------------------------------------------------------------------------
def split_box(src_w: int, src_h: int, fx: float, fy: float) -> tuple[int, int, int, int]:
    """Retângulo (x, y, w, h) com proporção 1080:960 em volta de um rosto (rosto a ~42% da altura)."""
    sw = int(min(src_w * 0.5, src_h * OUT_W / (OUT_H / 2))) // 2 * 2
    sh = int(sw * (OUT_H / 2) / OUT_W) // 2 * 2
    x = int(np.clip(fx * src_w - sw / 2, 0, src_w - sw))
    y = int(np.clip(fy * src_h - 0.42 * sh, 0, src_h - sh))
    return x, y, sw, sh


def frame_crop(frame: np.ndarray, tr: Track, i: int, compose: bool) -> np.ndarray:
    import cv2

    i = min(i, tr.n - 1)
    h, w = frame.shape[:2]
    if tr.layout[i] == 1 and tr.split[i]:
        ax, ay, bx, by = tr.split[i]  # type: ignore[misc]
        out = np.empty((OUT_H, OUT_W, 3), np.uint8)
        for k, (fx, fy) in enumerate(((ax, ay), (bx, by))):
            x, y, sw, sh = split_box(w, h, fx, fy)
            out[k * OUT_H // 2:(k + 1) * OUT_H // 2] = cv2.resize(frame[y:y + sh, x:x + sw], (OUT_W, OUT_H // 2),
                                                                interpolation=cv2.INTER_CUBIC)
        return out
    cw = tr.crop_w
    x = int(np.clip(round(tr.cx[i] * w - cw / 2), 0, w - cw)) // 2 * 2
    crop = frame[:, x:x + cw]
    if compose:
        return cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_CUBIC)
    return np.ascontiguousarray(crop)


def render_piped(source: Path, start: float, end: float, tr: Track, encode_args_after_input: list[str],
                 output: Path, cwd: Path, on_progress: Callable[[float], None], is_canceled: Callable[[], bool],
                 register_process: Callable | None = None) -> None:
    """Decodifica a fonte (ffmpeg) → recorta em Python → codifica (ffmpeg, com áudio da fonte).

    Sem split, envia o crop no tamanho nativo e o ffmpeg amplia (menos dados no pipe);
    com split, compõe 1080×1920 aqui.
    """
    dur = end - start
    compose = any(tr.layout)
    in_w, in_h = (OUT_W, OUT_H) if compose else (tr.crop_w, tr.src_h)
    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-an",
         "-vf", f"fps={tr.fps},scale={tr.src_w}:{tr.src_h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    enc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{in_w}x{in_h}", "-r", str(tr.fps), "-i", "-",
         "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source), *encode_args_after_input, str(output)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=cwd)
    for p in (dec, enc):
        if register_process:
            register_process(p)
    errs: dict[str, deque] = {"dec": deque(maxlen=30), "enc": deque(maxlen=30)}

    def drain(name: str, stream) -> None:
        for line in iter(stream.readline, b""):
            errs[name].append(line.decode("utf-8", "replace").rstrip())

    threads = [threading.Thread(target=drain, args=("dec", dec.stderr), daemon=True),
               threading.Thread(target=drain, args=("enc", enc.stderr), daemon=True)]
    for t in threads:
        t.start()

    frame_bytes = tr.src_w * tr.src_h * 3
    buf = bytearray(frame_bytes)
    i = 0
    canceled = False
    try:
        assert dec.stdout and enc.stdin
        while True:
            if is_canceled():
                canceled = True
                break
            n = dec.stdout.readinto(buf)
            if not n or n < frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(tr.src_h, tr.src_w, 3)
            enc.stdin.write(frame_crop(frame, tr, i, compose).tobytes())
            i += 1
            if i % 15 == 0:
                on_progress(min(98.0, 100 * i / tr.n))
    except BrokenPipeError:
        pass  # encoder morreu: o erro vem do stderr dele
    finally:
        try:
            if enc.stdin:
                enc.stdin.close()
        except BrokenPipeError:
            pass
        if canceled:
            for p in (dec, enc):
                if p.poll() is None:
                    p.terminate()
        dec.wait()
        enc.wait()
        for t in threads:
            t.join(timeout=2)
    if canceled:
        raise ReframeCanceled()
    if enc.returncode != 0:
        raise ReframeError("Falha ao codificar o corte reenquadrado", "\n".join(errs["enc"]))
    if i == 0:
        raise ReframeError("Não foi possível ler os frames da fonte", "\n".join(errs["dec"]))
