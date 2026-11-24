import { useEffect, useMemo, useRef } from 'react'
import { captionSpans, clipWords, spanAt } from '@/lib/captions'
import { assFontPx } from '@/lib/fonts'
import { OUT_H, OUT_W, singleCrop, splitBox } from '@/lib/crop'
import { useEditor } from '@/stores/editor'
import { useEditorCtx, useVideoTime } from './context'
import { useLayoutAt } from './layout'

const PREVIEW_W = 324
const PREVIEW_H = (PREVIEW_W * OUT_H) / OUT_W // 576

function PreviewCanvas() {
  const { videoRef } = useEditorCtx()
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const layoutAt = useLayoutAt()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const layoutRef = useRef(layoutAt)
  const startRef = useRef(start)
  useEffect(() => {
    layoutRef.current = layoutAt
    startRef.current = start
  })

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = PREVIEW_W * dpr
    canvas.height = PREVIEW_H * dpr
    const W = canvas.width
    const H = canvas.height
    let raf = 0
    const draw = () => {
      raf = requestAnimationFrame(draw)
      const v = videoRef.current
      if (!v || v.readyState < 2 || !v.videoWidth) return
      const vw = v.videoWidth
      const vh = v.videoHeight
      const layout = layoutRef.current(v.currentTime - startRef.current)
      ctx.imageSmoothingQuality = 'high'
      if (layout === 'blur') {
        // fundo: vídeo ampliado e borrado; frente: vídeo inteiro centralizado
        const cover = Math.max(W / vw, H / vh)
        ctx.filter = 'blur(14px) brightness(0.92)'
        ctx.drawImage(v, (W - vw * cover) / 2, (H - vh * cover) / 2, vw * cover, vh * cover)
        ctx.filter = 'none'
        const fit = Math.min(W / vw, H / vh)
        ctx.drawImage(v, (W - vw * fit) / 2, (H - vh * fit) / 2, vw * fit, vh * fit)
        return
      }
      if (layout.kind === 'gameplay') {
        const { cam, game, top_ratio } = layout.g
        const topH = Math.round(H * top_ratio)
        if (cam) ctx.drawImage(v, cam[0] * vw, cam[1] * vh, cam[2] * vw, cam[3] * vh, 0, 0, W, topH)
        ctx.drawImage(v, game[0] * vw, game[1] * vh, game[2] * vw, game[3] * vh, 0, topH, W, H - topH)
        return
      }
      if (layout.kind === 'split') {
        for (const [k, [fx, fy]] of [layout.a, layout.b].entries()) {
          const r = splitBox(vw, vh, fx, fy)
          ctx.drawImage(v, r.x, r.y, r.w, r.h, 0, (k * H) / 2, W, H / 2)
        }
        return
      }
      const r = singleCrop(vw, vh, layout.cx)
      ctx.drawImage(v, r.x, r.y, r.w, r.h, 0, 0, W, H)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [videoRef])

  return <canvas ref={canvasRef} style={{ width: PREVIEW_W, height: PREVIEW_H }} className="absolute inset-0" />
}

function CaptionOverlay() {
  const { words, style } = useEditorCtx()
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const end = useEditor((s) => s.draft?.end_s ?? 0)
  const overrides = useEditor((s) => s.draft?.words)
  const titleOverlay = useEditor((s) => s.draft?.title_overlay ?? '')
  const titleUntil = useEditor((s) => s.draft?.title_until ?? null)
  const t = useVideoTime(60) - start

  const spans = useMemo(
    () => captionSpans(clipWords(words, start, end, overrides ?? {}), style.words_per_line, style.animation, end - start),
    [words, start, end, overrides, style.words_per_line, style.animation],
  )
  const span = t >= 0 && t <= end - start ? spanAt(spans, t) : null
  const showTitle = !!titleOverlay.trim() && t >= 0 && t <= end - start && (titleUntil === null || t < titleUntil)

  const upper = (s: string) => (style.uppercase ? s.toLocaleUpperCase('pt-BR') : s)
  const strokeW = style.outline_px * 2 // o contorno do ASS fica todo do lado de fora; o stroke do CSS é centrado

  return (
    // camada lógica 1080×1920 escalada para o tamanho do preview (mesmas unidades do .ass)
    <div
      className="pointer-events-none absolute top-0 left-0 origin-top-left"
      style={{ width: OUT_W, height: OUT_H, transform: `scale(${PREVIEW_W / OUT_W})` }}
    >
      {showTitle && (
        <div className="absolute inset-x-0 flex justify-center" style={{ top: 170 }}>
          <span
            style={{ fontFamily: 'Montserrat ExtraBold', fontSize: assFontPx('Montserrat ExtraBold', 64), padding: '10px 18px' }}
            className="max-w-[960px] bg-white text-center leading-tight text-black"
          >
            {titleOverlay}
          </span>
        </div>
      )}
      {span && (
        <div
          className="absolute inset-x-0 text-center whitespace-nowrap"
          style={{
            top: style.position_y * OUT_H,
            transform: 'translateY(-50%)',
            fontFamily: style.font,
            fontSize: assFontPx(style.font, style.font_size),
            lineHeight: 1.2,
            color: style.primary_color,
            WebkitTextStroke: strokeW > 0 ? `${strokeW}px ${style.outline_color}` : undefined,
            paintOrder: 'stroke fill',
            textShadow: style.shadow_px > 0 ? `${style.shadow_px}px ${style.shadow_px}px 0 rgba(0,0,0,0.5)` : undefined,
          }}
        >
          {span.line.map((w, i) => {
            const cur = span.current
            const highlighted =
              cur !== null && style.animation !== 'none' && (style.animation === 'karaoke' ? i <= cur : i === cur)
            const pop = style.animation === 'pop' && i === cur
            return (
              <span key={pop ? `${i}-${span.s}` : i}>
                {i > 0 && ' '}
                <span
                  className={pop ? 'inline-block animate-[caption-pop_120ms_ease-out]' : undefined}
                  style={highlighted ? { color: style.highlight_color } : undefined}
                >
                  {upper(w)}
                </span>
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function Preview() {
  const { track, trackStale } = useEditorCtx()
  const mode = useEditor((s) => s.draft?.reframe_mode)
  const waitingFaces = (mode === 'auto' || mode === 'split' || mode === 'speaker' || mode === 'gameplay') && track === null
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative overflow-hidden rounded-xl bg-black shadow-lg ring-1 ring-border" style={{ width: PREVIEW_W, height: PREVIEW_H }}>
        <PreviewCanvas />
        <CaptionOverlay />
      </div>
      <p className="h-4 text-center text-[11px] text-muted-foreground">
        {waitingFaces
          ? 'Análise de rostos em andamento — mostrando o centro por enquanto'
          : trackStale && (mode === 'auto' || mode === 'split' || mode === 'speaker')
            ? 'Recalculando o enquadramento…'
            : 'Preview sem render · 1080×1920'}
      </p>
    </div>
  )
}
