import { create } from 'zustand'
import type { Clip } from '@/api/types'
import type { LayoutOverrides } from '@/lib/crop'

export interface StyleFields {
  font: string
  font_size: number
  primary_color: string
  highlight_color: string
  outline_color: string
  outline_px: number
  shadow_px: number
  uppercase: boolean
  words_per_line: number
  position_y: number
  animation: 'highlight' | 'pop' | 'karaoke' | 'none'
}

export interface Keyframe {
  t: number // relativo ao início do corte
  x: number // centro do crop, normalizado
}

export interface Draft {
  start_s: number
  end_s: number
  title: string
  title_overlay: string
  title_until: number | null
  reframe_mode: Clip['reframe_mode']
  keyframes: Keyframe[]
  layout: LayoutOverrides // gameplay: tamanho/posição da webcam e do jogo
  caption_style_id: number | null
  style: Partial<StyleFields>
  words: Record<string, string>
  quality: 'high' | 'normal' | 'small'
  normalize_audio: boolean | null // null = usar o padrão das Configurações
}

function parse<T>(raw: string, fallback: T): T {
  try {
    const v = JSON.parse(raw || '')
    return v ?? fallback
  } catch {
    return fallback
  }
}

export function draftFromClip(c: Clip): Draft {
  const ov = parse<Record<string, unknown>>(c.caption_overrides_json, {})
  const structured = 'words' in ov || 'style' in ov || 'title_until' in ov
  const exp = parse<{ quality?: Draft['quality']; normalize_audio?: boolean }>(c.export_json ?? '{}', {})
  const kf = parse<Keyframe[]>(c.manual_crop_json, [])
  return {
    start_s: c.start_s,
    end_s: c.end_s,
    title: c.title,
    title_overlay: c.title_overlay,
    title_until: structured && typeof ov.title_until === 'number' ? ov.title_until : null,
    reframe_mode: c.reframe_mode,
    keyframes: Array.isArray(kf) ? kf.filter((k) => typeof k?.t === 'number' && typeof k?.x === 'number') : [],
    layout: parse<LayoutOverrides>(c.layout_json ?? '{}', {}),
    caption_style_id: c.caption_style_id,
    style: structured ? ((ov.style as Partial<StyleFields>) ?? {}) : {},
    words: (structured ? (ov.words as Record<string, string>) : (ov as Record<string, string>)) ?? {},
    quality: exp.quality ?? 'normal',
    normalize_audio: typeof exp.normalize_audio === 'boolean' ? exp.normalize_audio : null,
  }
}

/** Campos do PATCH /clips/{id} a partir do rascunho. */
export function draftToPatch(d: Draft): Record<string, unknown> {
  const overrides: Record<string, unknown> = { words: d.words, style: d.style }
  if (d.title_until) overrides.title_until = d.title_until
  const exp: Record<string, unknown> = { quality: d.quality }
  if (d.normalize_audio !== null) exp.normalize_audio = d.normalize_audio
  return {
    start_s: Math.round(d.start_s * 1000) / 1000,
    end_s: Math.round(d.end_s * 1000) / 1000,
    title: d.title,
    title_overlay: d.title_overlay,
    reframe_mode: d.reframe_mode,
    manual_crop_json: JSON.stringify(d.keyframes),
    layout_json: JSON.stringify(d.layout),
    caption_style_id: d.caption_style_id,
    caption_overrides_json: JSON.stringify(overrides),
    export_json: JSON.stringify(exp),
  }
}

/** Só os campos que mudaram desde o último salvamento. */
export function patchDiff(saved: Draft | null, d: Draft): Record<string, unknown> {
  const now = draftToPatch(d)
  if (!saved) return now
  const before = draftToPatch(saved)
  return Object.fromEntries(Object.entries(now).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k])))
}

const HISTORY_LIMIT = 200
const COALESCE_MS = 1000

interface EditorState {
  clipId: number | null
  draft: Draft | null
  saved: Draft | null
  past: Draft[]
  future: Draft[]
  lastKey: string | null
  lastAt: number
  liveX: number | null // retângulo arrastado na fonte (manual), antes de virar keyframe
  load: (c: Clip) => void
  /** Altera o rascunho. `key` agrupa edições seguidas do mesmo controle num único passo de desfazer. */
  set: (patch: Partial<Draft>, key?: string) => void
  /** Ponto de desfazer explícito (início de um arraste); edições seguintes usam `set(patch, 'gesture')`. */
  checkpoint: () => void
  undo: () => void
  redo: () => void
  markSaved: (d: Draft) => void
  setLiveX: (x: number | null) => void
}

export const useEditor = create<EditorState>((set, get) => ({
  clipId: null,
  draft: null,
  saved: null,
  past: [],
  future: [],
  lastKey: null,
  lastAt: 0,
  liveX: null,
  load: (c) => {
    const d = draftFromClip(c)
    set({ clipId: c.id, draft: d, saved: d, past: [], future: [], lastKey: null, lastAt: 0, liveX: null })
  },
  set: (patch, key) => {
    const { draft, past, lastKey, lastAt } = get()
    if (!draft) return
    const now = Date.now()
    const coalesce = key !== undefined && (key === 'gesture' || (key === lastKey && now - lastAt < COALESCE_MS))
    set({
      draft: { ...draft, ...patch },
      past: coalesce ? past : [...past, draft].slice(-HISTORY_LIMIT),
      future: [],
      lastKey: key ?? null,
      lastAt: now,
    })
  },
  checkpoint: () => {
    const { draft, past } = get()
    if (draft) set({ past: [...past, draft].slice(-HISTORY_LIMIT), future: [], lastKey: 'gesture', lastAt: Date.now() })
  },
  undo: () => {
    const { draft, past, future } = get()
    if (!draft || !past.length) return
    set({ draft: past[past.length - 1], past: past.slice(0, -1), future: [draft, ...future], lastKey: null, liveX: null })
  },
  redo: () => {
    const { draft, past, future } = get()
    if (!draft || !future.length) return
    set({ draft: future[0], past: [...past, draft], future: future.slice(1), lastKey: null, liveX: null })
  },
  markSaved: (d) => set({ saved: d }),
  setLiveX: (x) => set({ liveX: x }),
}))
