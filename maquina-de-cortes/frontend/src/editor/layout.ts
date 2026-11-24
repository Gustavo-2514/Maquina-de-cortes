import { gameplayBoxes, manualCx, trackAt, type FrameLayout } from '@/lib/crop'
import { useEditor } from '@/stores/editor'
import { useEditorCtx } from './context'

export type LayoutAt = (t: number) => FrameLayout | 'blur'

/** Layout de cada frame (tempo relativo ao corte) conforme o rascunho — usado pelo preview e pela fonte. */
export function useLayoutAt(): LayoutAt {
  const { track, project } = useEditorCtx()
  const mode = useEditor((s) => s.draft?.reframe_mode ?? 'center')
  const keyframes = useEditor((s) => s.draft?.keyframes ?? [])
  const layout = useEditor((s) => s.draft?.layout ?? {})
  const liveX = useEditor((s) => s.liveX)
  const srcW = project.width || 16
  const srcH = project.height || 9
  return (t: number) => {
    if (mode === 'blur_fit') return 'blur'
    if (mode === 'manual') return { kind: 'single', cx: liveX ?? manualCx(keyframes, t) }
    if (mode === 'gameplay') {
      // recalculado aqui com os ajustes do rascunho → arrastar a webcam/jogo reflete na hora
      const g = gameplayBoxes(srcW, srcH, track?.gameplay?.cam_face, layout)
      return g.cam ? { kind: 'gameplay', g } : 'blur' // sem webcam: jogo inteiro com fundo borrado
    }
    if ((mode === 'auto' || mode === 'split' || mode === 'speaker') && track) return trackAt(track, t)
    return { kind: 'single', cx: 0.5 }
  }
}
