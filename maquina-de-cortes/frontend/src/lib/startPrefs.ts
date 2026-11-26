import type { AnalysisOptions, Template } from '@/api/types'

/** Escolhas feitas ao colar o link (tipo de conteúdo + renderizar ao final), lembradas entre visitas. */
export interface StartPrefs {
  template: string
  reframe_mode: AnalysisOptions['reframe_mode']
  caption_style: string
  auto_render: boolean
}

const KEY = 'mdc.startPrefs'
const DEFAULT: StartPrefs = { template: 'geral', reframe_mode: 'auto', caption_style: 'hormozi', auto_render: false }

export function loadStartPrefs(): StartPrefs {
  try {
    return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
  } catch {
    return DEFAULT
  }
}

export function saveStartPrefs(p: StartPrefs) {
  localStorage.setItem(KEY, JSON.stringify(p))
}

export const prefsFromTemplate = (t: Template, auto_render: boolean): StartPrefs => ({
  template: t.key,
  reframe_mode: t.reframe_mode,
  caption_style: t.caption_style,
  auto_render,
})
