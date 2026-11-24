/** Geometria do enquadramento e encaixe nas palavras — espelha reframer.py / highlighter.py. */

export const OUT_W = 1080
export const OUT_H = 1920

export interface GameplayLayout {
  cam: number[] | null // [x, y, w, h] normalizados
  game: number[]
  top_ratio: number
  cam_detected: boolean
  cam_face?: number[] | null // [cx, cy, w, h] do rosto detectado na webcam
}

/** Ajustes do editor no layout de gameplay (Clip.layout_json). */
export interface LayoutOverrides {
  top_ratio?: number
  cam_center?: [number, number]
  cam_w?: number
  game_cx?: number
}

export interface CropTrack {
  mode: string
  fps: number
  src_w: number
  src_h: number
  frames: number
  crop_w: number
  crop_w_norm: number
  cuts: number[]
  layout: number[]
  cx: number[]
  split: (number[] | null)[]
  switches?: number[]
  gameplay?: GameplayLayout | null
}

/** Largura do crop 9:16 em px da fonte (altura = altura da fonte). */
export function cropWidth(srcW: number, srcH: number): number {
  return Math.min(srcW, Math.floor((srcH * 9) / 16 / 2) * 2)
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

/** Retângulo 1080:960 em volta de um rosto (igual ao split_box do Python). */
export function splitBox(srcW: number, srcH: number, fx: number, fy: number): Rect {
  const sw = Math.floor(Math.min(srcW * 0.5, (srcH * OUT_W) / (OUT_H / 2)) / 2) * 2
  const sh = Math.floor((sw * (OUT_H / 2)) / OUT_W / 2) * 2
  const x = Math.min(Math.max(fx * srcW - sw / 2, 0), srcW - sw)
  const y = Math.min(Math.max(fy * srcH - 0.42 * sh, 0), srcH - sh)
  return { x: Math.round(x), y: Math.round(y), w: sw, h: sh }
}

/** Crop simples (1 retângulo) com centro cx normalizado, limitado ao quadro. */
export function singleCrop(srcW: number, srcH: number, cx: number): Rect {
  const cw = cropWidth(srcW, srcH)
  const x = Math.min(Math.max(Math.round(cx * srcW - cw / 2), 0), srcW - cw)
  return { x, y: 0, w: cw, h: srcH }
}

export type FrameLayout =
  | { kind: 'single'; cx: number }
  | { kind: 'split'; a: [number, number]; b: [number, number] }
  | { kind: 'gameplay'; g: GameplayLayout }

/** Layout no tempo relativo t (frame mais próximo; fora do corte usa as pontas). */
export function trackAt(track: CropTrack, t: number): FrameLayout {
  if (track.gameplay) return { kind: 'gameplay', g: track.gameplay }
  if (!track.frames) return { kind: 'single', cx: 0.5 }
  const i = Math.min(track.frames - 1, Math.max(0, Math.floor(t * track.fps)))
  const sp = track.split[i]
  if (track.layout[i] === 1 && sp) return { kind: 'split', a: [sp[0], sp[1]], b: [sp[2], sp[3]] }
  return { kind: 'single', cx: track.cx[i] ?? 0.5 }
}

/** Interpolação de keyframes manuais com smoothstep (igual ao Python). */
export function manualCx(keyframes: { t: number; x: number }[], t: number): number {
  if (!keyframes.length) return 0.5
  const kf = [...keyframes].sort((a, b) => a.t - b.t)
  if (t <= kf[0].t) return kf[0].x
  if (t >= kf[kf.length - 1].t) return kf[kf.length - 1].x
  for (let i = 0; i < kf.length - 1; i++) {
    const a = kf[i]
    const b = kf[i + 1]
    if (t >= a.t && t <= b.t) {
      let u = (t - a.t) / Math.max(b.t - a.t, 1e-6)
      u = u * u * (3 - 2 * u)
      return a.x + (b.x - a.x) * u
    }
  }
  return kf[kf.length - 1].x
}

// --- Encaixe nas palavras (timeline / transcrição) ---------------------------------
interface TW {
  s: number
  e: number
}

export const END_BREATH_S = 0.15

/** Início da palavra mais próxima de t. */
export function snapStart(words: TW[], t: number): number {
  if (!words.length) return t
  let best = words[0]
  for (const w of words) if (Math.abs(w.s - t) < Math.abs(best.s - t)) best = w
  return best.s
}

/** Fim da palavra mais próxima + respiro sem invadir a próxima (igual ao end_time do Python). */
export function snapEnd(words: TW[], t: number, duration = Infinity): number {
  if (!words.length) return t
  let bi = 0
  words.forEach((w, i) => {
    if (Math.abs(w.e - t) < Math.abs(words[bi].e - t)) bi = i
  })
  const e = words[bi].e
  const next = bi + 1 < words.length ? words[bi + 1].s - 0.02 : Infinity
  return Math.round(Math.min(e + END_BREATH_S, Math.max(e, next), duration) * 1000) / 1000
}

const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/** Igual a reframer.GAMEPLAY_TOP_RATIO (Python). */
export const GAMEPLAY_TOP_RATIO = 0.32

/** Espelho de reframer.gameplay_boxes (Python): caixas da webcam e do jogo com os ajustes do editor. */
export function gameplayBoxes(srcW: number, srcH: number, camFace: number[] | null | undefined, layout: LayoutOverrides = {}): GameplayLayout {
  const r = clamp(layout.top_ratio ?? GAMEPLAY_TOP_RATIO, 0.25, 0.6)
  const topH = Math.floor(Math.round(r * OUT_H) / 2) * 2
  const botH = OUT_H - topH
  const topAspect = OUT_W / topH
  const botAspect = OUT_W / botH
  const box = (x: number, y: number, w: number, h: number) => {
    w = Math.min(w, 1)
    h = Math.min(h, 1)
    return [clamp(x, 0, 1 - w), clamp(y, 0, 1 - h), w, h]
  }
  let cam: number[] | null = null
  let center = layout.cam_center ?? null
  let camW = layout.cam_w ?? 0.3
  if (!center && camFace) {
    const chPx = camFace[3] * srcH * 1.8
    const cwPx = chPx * topAspect
    center = [camFace[0], camFace[1] + (0.05 * chPx) / srcH]
    camW = layout.cam_w ?? cwPx / srcW
  }
  if (center) {
    let cwPx = camW * srcW
    let chPx = cwPx / topAspect
    if (chPx > srcH) {
      chPx = srcH
      cwPx = chPx * topAspect
    }
    cam = box(center[0] - cwPx / srcW / 2, center[1] - chPx / srcH / 2, cwPx / srcW, chPx / srcH)
  }
  const gwPx = Math.min(srcW, srcH * botAspect)
  const ghPx = gwPx / botAspect
  const gcx = layout.game_cx ?? 0.5
  const game = box(gcx - gwPx / srcW / 2, 0.5 - ghPx / srcH / 2, gwPx / srcW, ghPx / srcH)
  return { cam, game, top_ratio: topH / OUT_H, cam_detected: !!camFace, cam_face: camFace ?? null }
}
