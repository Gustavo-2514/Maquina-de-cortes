import { useRef } from 'react'
import { mediaUrl } from '@/api/projects'
import { cropWidth, manualCx, splitBox } from '@/lib/crop'
import { useEditor } from '@/stores/editor'
import { useEditorCtx, useVideoTime } from './context'
import { useLayoutAt } from './layout'

type Role = 'crop' | 'cam' | 'game' | 'view'
interface Rect {
  left: number
  top: number
  w: number
  h: number
  role: Role
  label?: string
}

/** Vídeo-fonte (proxy) com os retângulos do enquadramento.
 * Manual: arraste o crop. Gameplay: arraste a webcam (qualquer direção) e o jogo (horizontal). */
export function SourceView() {
  const { videoRef, project } = useEditorCtx()
  const mode = useEditor((s) => s.draft?.reframe_mode ?? 'center')
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const keyframes = useEditor((s) => s.draft?.keyframes ?? [])
  const layoutOv = useEditor((s) => s.draft?.layout ?? {})
  const liveX = useEditor((s) => s.liveX)
  const setLiveX = useEditor((s) => s.setLiveX)
  const setDraft = useEditor((s) => s.set)
  const checkpoint = useEditor((s) => s.checkpoint)
  const layoutAt = useLayoutAt()
  const t = useVideoTime(30) - start
  const boxRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ role: Role; x0: number; y0: number; a: number; b: number } | null>(null)

  const srcW = project.width || 16
  const srcH = project.height || 9
  const cwn = cropWidth(srcW, srcH) / srcW

  const layout = layoutAt(t)
  let rects: Rect[]
  if (layout === 'blur') rects = [{ left: 0, top: 0, w: 1, h: 1, role: 'view', label: mode === 'gameplay' ? 'webcam não detectada — jogo inteiro' : undefined }]
  else if (layout.kind === 'gameplay') {
    const { cam, game } = layout.g
    rects = [{ left: game[0], top: game[1], w: game[2], h: game[3], role: 'game', label: 'jogo (embaixo)' }]
    if (cam) rects.push({ left: cam[0], top: cam[1], w: cam[2], h: cam[3], role: 'cam', label: 'webcam (em cima)' })
  } else if (layout.kind === 'split')
    rects = [layout.a, layout.b].map(([fx, fy], i) => {
      const r = splitBox(srcW, srcH, fx, fy)
      return { left: r.x / srcW, top: r.y / srcH, w: r.w / srcW, h: r.h / srcH, role: 'view' as const, label: i ? 'baixo' : 'cima' }
    })
  else {
    const cx = Math.min(Math.max(layout.cx, cwn / 2), 1 - cwn / 2)
    rects = [{ left: cx - cwn / 2, top: 0, w: cwn, h: 1, role: mode === 'manual' ? 'crop' : 'view' }]
  }
  const dim = rects.length === 1 && rects[0].w < 0.99 ? rects[0] : null // escurece o que fica fora de um crop simples
  const draggable = (r: Rect) => r.role === 'crop' || r.role === 'cam' || r.role === 'game'

  const onPointerDown = (r: Rect) => (e: React.PointerEvent) => {
    if (!draggable(r)) return
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    if (r.role === 'crop') drag.current = { role: 'crop', x0: e.clientX, y0: e.clientY, a: liveX ?? manualCx(keyframes, t), b: 0 }
    else {
      checkpoint()
      drag.current = { role: r.role, x0: e.clientX, y0: e.clientY, a: r.left + r.w / 2, b: r.top + r.h / 2 }
    }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || !boxRef.current) return
    const dx = (e.clientX - d.x0) / boxRef.current.clientWidth
    const dy = (e.clientY - d.y0) / boxRef.current.clientHeight
    if (d.role === 'crop') setLiveX(Math.min(Math.max(d.a + dx, cwn / 2), 1 - cwn / 2))
    else if (d.role === 'game') setDraft({ layout: { ...layoutOv, game_cx: Math.round((d.a + dx) * 1000) / 1000 } }, 'gesture')
    else if (d.role === 'cam') {
      const cam = layout !== 'blur' && layout.kind === 'gameplay' ? layout.g.cam : null
      setDraft(
        {
          layout: {
            ...layoutOv,
            cam_center: [Math.round((d.a + dx) * 1000) / 1000, Math.round((d.b + dy) * 1000) / 1000],
            cam_w: layoutOv.cam_w ?? (cam ? Math.round(cam[2] * 1000) / 1000 : 0.3),
          },
        },
        'gesture',
      )
    }
  }
  const onPointerUp = () => {
    drag.current = null
  }

  return (
    <div ref={boxRef} className="relative w-full overflow-hidden rounded-xl bg-black" style={{ aspectRatio: `${srcW} / ${srcH}` }}>
      <video
        ref={videoRef}
        src={mediaUrl(project.id, 'proxy.mp4')}
        preload="auto"
        playsInline
        className="absolute inset-0 size-full"
        onLoadedMetadata={(e) => {
          e.currentTarget.currentTime = start
        }}
      />
      {/* escurece o que fica fora do corte */}
      {dim && (
        <>
          <div className="pointer-events-none absolute inset-y-0 left-0 bg-black/55" style={{ width: `${dim.left * 100}%` }} />
          <div className="pointer-events-none absolute inset-y-0 right-0 bg-black/55" style={{ width: `${(1 - dim.left - dim.w) * 100}%` }} />
        </>
      )}
      {rects.map((r, i) => (
        <div
          key={`${r.role}-${i}`}
          onPointerDown={onPointerDown(r)}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className={
            draggable(r)
              ? `absolute border-2 shadow-[0_0_0_1px_rgba(0,0,0,.5)] ${r.role === 'cam' ? 'cursor-move border-sky-400' : r.role === 'game' ? 'cursor-ew-resize border-amber-400' : 'cursor-grab border-primary active:cursor-grabbing'}`
              : 'pointer-events-none absolute border-2 border-white/80 shadow-[0_0_0_1px_rgba(0,0,0,.5)]'
          }
          style={{ left: `${r.left * 100}%`, top: `${r.top * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }}
        >
          {r.label && <span className="absolute top-1 left-1 rounded bg-black/70 px-1 text-[10px] whitespace-nowrap text-white">{r.label}</span>}
        </div>
      ))}
      {mode === 'gameplay' && rects.some((r) => r.role === 'cam') && (
        <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 text-[11px] text-white">
          Arraste a webcam (azul) e o jogo (amarelo)
        </span>
      )}
      {mode === 'manual' && (
        <span className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/70 px-2 py-0.5 text-[11px] text-white">
          Arraste o retângulo · depois “Adicionar keyframe”
        </span>
      )}
    </div>
  )
}
