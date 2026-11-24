import { createContext, useContext, useEffect, useState, type RefObject } from 'react'
import type { CaptionStyle, Clip, Project } from '@/api/types'
import type { CWord } from '@/lib/captions'
import type { CropTrack } from '@/lib/crop'
import type { StyleFields } from '@/stores/editor'

export interface EditorCtx {
  videoRef: RefObject<HTMLVideoElement | null>
  project: Project
  clip: Clip
  words: CWord[] // transcrição inteira (tempos absolutos)
  track: CropTrack | null | undefined // trilha do servidor (auto/split); null = análise de rostos pendente
  trackStale: boolean // a trilha é de uma versão anterior do corte (salvando / recalculando)
  baseStyle: CaptionStyle | undefined // preset efetivo
  style: StyleFields // preset + ajustes do corte
  fps: number
}

export const EditorContext = createContext<EditorCtx | null>(null)

export function useEditorCtx(): EditorCtx {
  const ctx = useContext(EditorContext)
  if (!ctx) throw new Error('fora do editor')
  return ctx
}

/** currentTime do vídeo, atualizado em até `hz` vezes por segundo (só re-renderiza quem usa). */
export function useVideoTime(hz = 30): number {
  const { videoRef } = useEditorCtx()
  const [t, setT] = useState(0)
  useEffect(() => {
    let raf = 0
    let last = 0
    const loop = (now: number) => {
      const v = videoRef.current
      if (v && now - last >= 1000 / hz) {
        last = now
        setT(v.currentTime)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [videoRef, hz])
  return t
}
