import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useThumbs, useWaveform } from '@/api/editor'
import { formatTime } from '@/lib/clip'
import { snapEnd, snapStart } from '@/lib/crop'
import { useEditor } from '@/stores/editor'
import { useEditorCtx } from './context'

const CONTEXT_S = 30
const MIN_CLIP_S = 1
const WAVE_H = 64
const THUMB_H = 44
const RULER_H = 18

type DragKind = 'start' | 'end' | 'move' | 'scrub'

function tickStep(pps: number): number {
  for (const s of [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]) if (s * pps >= 70) return s
  return 600
}

export function Timeline() {
  const { videoRef, project, words } = useEditorCtx()
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const end = useEditor((s) => s.draft?.end_s ?? 0)
  const setDraft = useEditor((s) => s.set)
  const checkpoint = useEditor((s) => s.checkpoint)
  const { data: wave } = useWaveform(project.id)
  const { data: thumbs } = useThumbs(project.id)
  const duration = project.duration_s ?? Math.max(end + CONTEXT_S, 60)

  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const playheadRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(800)
  const [view, setView] = useState<[number, number]>(() => [Math.max(0, start - CONTEXT_S), Math.min(duration, end + CONTEXT_S)])
  const drag = useRef<{ kind: DragKind; t0: number; s0: number; e0: number } | null>(null)
  const [dragging, setDragging] = useState<DragKind | null>(null)

  const [vs, ve] = view
  const pps = width / Math.max(0.1, ve - vs)
  const xOf = useCallback((t: number) => (t - vs) * pps, [vs, pps])

  useLayoutEffect(() => {
    const el = boxRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  // se o corte sair da janela visível (desfazer, atalhos I/O…), reposiciona a janela
  useEffect(() => {
    if (drag.current) return
    setView(([a, b]) => {
      if (start >= a && end <= b) return [a, b]
      const span = Math.max(b - a, end - start + 10)
      const mid = (start + end) / 2
      const na = Math.max(0, Math.min(mid - span / 2, duration - span))
      return [na, Math.min(duration, na + span)]
    })
  }, [start, end, duration])

  // forma de onda
  useEffect(() => {
    const c = canvasRef.current
    const ctx = c?.getContext('2d')
    if (!c || !ctx) return
    const dpr = window.devicePixelRatio || 1
    c.width = width * dpr
    c.height = WAVE_H * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, WAVE_H)
    if (!wave) return
    const css = getComputedStyle(document.documentElement)
    const inside = css.getPropertyValue('--primary').trim() || '#8b5cf6'
    const outside = css.getPropertyValue('--muted-foreground').trim() || '#888'
    const mid = WAVE_H / 2
    for (let x = 0; x < width; x++) {
      const t0 = vs + x / pps
      const i0 = Math.max(0, Math.floor(t0 * wave.rate))
      const i1 = Math.min(wave.length, Math.max(i0 + 1, Math.floor((t0 + 1 / pps) * wave.rate)))
      let peak = 0
      for (let i = i0; i < i1; i++) if (wave.peaks[i] > peak) peak = wave.peaks[i]
      const h = Math.max(1, peak * (WAVE_H - 6))
      ctx.fillStyle = t0 >= start && t0 <= end ? inside : outside
      ctx.globalAlpha = t0 >= start && t0 <= end ? 0.95 : 0.45
      ctx.fillRect(x, mid - h / 2, 1, h)
    }
    ctx.globalAlpha = 1
  }, [wave, width, vs, pps, start, end])

  // playhead sem re-render do React
  useEffect(() => {
    let raf = 0
    const loop = () => {
      const v = videoRef.current
      if (v && playheadRef.current) {
        const x = (v.currentTime - vs) * pps
        playheadRef.current.style.transform = `translateX(${x}px)`
        playheadRef.current.style.opacity = x < 0 || x > width ? '0' : '1'
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [videoRef, vs, pps, width])

  const tAt = (clientX: number) => {
    const r = boxRef.current!.getBoundingClientRect()
    return Math.min(duration, Math.max(0, vs + (clientX - r.left) / pps))
  }

  const seek = (t: number) => {
    const v = videoRef.current
    if (v) v.currentTime = t
  }

  const onPointerDown = (kind: DragKind) => (e: React.PointerEvent) => {
    e.stopPropagation()
    e.preventDefault()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    const t = tAt(e.clientX)
    drag.current = { kind, t0: t, s0: start, e0: end }
    setDragging(kind)
    if (kind === 'scrub') seek(t)
    else checkpoint()
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const t = tAt(e.clientX)
    if (d.kind === 'scrub') return seek(t)
    if (d.kind === 'start') {
      const s = Math.min(Math.max(0, t), d.e0 - MIN_CLIP_S)
      setDraft({ start_s: s }, 'gesture')
      seek(s)
    } else if (d.kind === 'end') {
      const en = Math.max(Math.min(duration, t), d.s0 + MIN_CLIP_S)
      setDraft({ end_s: en }, 'gesture')
      seek(Math.max(d.s0, en - 0.05))
    } else {
      const dt = Math.min(Math.max(t - d.t0, -d.s0), duration - d.e0)
      setDraft({ start_s: d.s0 + dt, end_s: d.e0 + dt }, 'gesture')
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current
    drag.current = null
    setDragging(null)
    if (!d || d.kind === 'scrub' || e.altKey) return // Alt = sem encaixar na palavra
    const { draft } = useEditor.getState()
    if (!draft) return
    let s = draft.start_s
    let en = draft.end_s
    if (d.kind === 'start' || d.kind === 'move') s = snapStart(words, s)
    if (d.kind === 'end' || d.kind === 'move') en = snapEnd(words, en, duration)
    if (en - s >= MIN_CLIP_S) setDraft({ start_s: s, end_s: en }, 'gesture')
  }

  const zoom = (factor: number, center = videoRef.current?.currentTime ?? (start + end) / 2) => {
    const span = Math.min(duration, Math.max(4, (ve - vs) * factor))
    const a = Math.max(0, Math.min(center - span / 2, duration - span))
    setView([a, a + span])
  }
  const fit = () => setView([Math.max(0, start - CONTEXT_S), Math.min(duration, end + CONTEXT_S)])

  const onWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      zoom(e.deltaY > 0 ? 1.25 : 0.8, tAt(e.clientX))
      return
    }
    const dt = ((e.deltaX || e.deltaY) / pps) * 0.8
    const span = ve - vs
    const a = Math.max(0, Math.min(vs + dt, duration - span))
    setView([a, a + span])
  }

  const step = tickStep(pps)
  const ticks: number[] = []
  for (let t = Math.ceil(vs / step) * step; t <= ve; t += step) ticks.push(t)
  const thumbW = thumbs ? thumbs.every_s * pps : 0
  const thumbStride = thumbW > 0 ? Math.max(1, Math.ceil(60 / thumbW)) : 1

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums">
          Corte: {formatTime(start)} → {formatTime(end)} · <b className="text-foreground">{(end - start).toFixed(1)} s</b>
        </span>
        <span className="hidden md:inline">· arraste as alças (Alt = sem encaixar na palavra) · Ctrl+roda = zoom</span>
        <div className="ml-auto flex gap-1">
          <Button size="icon" variant="ghost" className="size-7" onClick={() => zoom(0.66)} aria-label="Aproximar">
            <ZoomIn />
          </Button>
          <Button size="icon" variant="ghost" className="size-7" onClick={() => zoom(1.5)} aria-label="Afastar">
            <ZoomOut />
          </Button>
          <Button size="icon" variant="ghost" className="size-7" onClick={fit} aria-label="Enquadrar o corte">
            <Maximize2 />
          </Button>
        </div>
      </div>
      <div
        ref={boxRef}
        className="relative cursor-text touch-none overflow-hidden rounded-lg border bg-muted/30 select-none"
        style={{ height: RULER_H + THUMB_H + WAVE_H }}
        onPointerDown={onPointerDown('scrub')}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onWheel={onWheel}
      >
        {/* régua */}
        <div className="absolute inset-x-0 top-0" style={{ height: RULER_H }}>
          {ticks.map((t) => (
            <span key={t} className="absolute top-0 border-l border-border pl-1 text-[10px] text-muted-foreground tabular-nums" style={{ left: xOf(t) }}>
              {formatTime(t).replace(/\.0$/, '')}
            </span>
          ))}
        </div>
        {/* miniaturas */}
        <div className="absolute inset-x-0 overflow-hidden" style={{ top: RULER_H, height: THUMB_H }}>
          {thumbs?.urls.map((u, i) => {
            if (i % thumbStride) return null
            const x = xOf(i * thumbs.every_s)
            const w = thumbW * thumbStride
            if (x + w < 0 || x > width) return null
            return (
              <img
                key={u}
                src={u}
                alt=""
                draggable={false}
                className="absolute top-0 h-full object-cover opacity-80"
                style={{ left: x, width: w }}
              />
            )
          })}
        </div>
        <canvas ref={canvasRef} className="absolute inset-x-0" style={{ top: RULER_H + THUMB_H, width, height: WAVE_H }} />

        {/* fora do corte escurecido */}
        <div className="pointer-events-none absolute inset-y-0 left-0 bg-background/55" style={{ width: Math.max(0, xOf(start)) }} />
        <div className="pointer-events-none absolute inset-y-0 right-0 bg-background/55" style={{ left: Math.min(width, xOf(end)) }} />

        {/* região do corte */}
        <div
          className="absolute inset-y-0 cursor-grab border-y-2 border-primary/80 active:cursor-grabbing"
          style={{ left: xOf(start), width: Math.max(2, (end - start) * pps), top: RULER_H }}
          onPointerDown={onPointerDown('move')}
          title="Arraste para mover o corte inteiro"
        />
        {(['start', 'end'] as const).map((k) => (
          <div
            key={k}
            onPointerDown={onPointerDown(k)}
            className={`absolute z-10 flex w-3 cursor-ew-resize items-center justify-center bg-primary ${k === 'start' ? 'rounded-l-md' : 'rounded-r-md'} ${dragging === k ? 'ring-2 ring-ring' : ''}`}
            style={{ left: xOf(k === 'start' ? start : end) - (k === 'start' ? 12 : 0), top: RULER_H, bottom: 0 }}
            aria-label={k === 'start' ? 'Início do corte' : 'Fim do corte'}
          >
            <span className="h-6 w-0.5 rounded bg-primary-foreground/80" />
          </div>
        ))}

        {/* playhead */}
        <div ref={playheadRef} className="pointer-events-none absolute inset-y-0 left-0 z-20 w-px bg-foreground">
          <span className="absolute -top-0 -left-1 size-2 rotate-45 bg-foreground" />
        </div>
      </div>
    </div>
  )
}
