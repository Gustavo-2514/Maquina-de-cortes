import { Ban, Download, FolderOpen, Loader2, Play, Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Checkbox, Input, NativeSelect, Progress } from '@/components/ui/input'
import { clipFileUrl, useClipActions } from '@/api/clips'
import { openFolder } from '@/api/downloads'
import { useCaptionStyles, useCreateStyle, useDeleteStyle } from '@/api/editor'
import { useJobActions, useJobs } from '@/api/jobs'
import type { CaptionStyle } from '@/api/types'
import { formatTime } from '@/lib/clip'
import { FONTS } from '@/lib/fonts'
import { GAMEPLAY_TOP_RATIO, manualCx, trackAt } from '@/lib/crop'
import { cn } from '@/lib/utils'
import { type StyleFields, useEditor } from '@/stores/editor'
import { useEditorCtx } from './context'

function Row({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="flex items-center justify-between text-xs font-medium">
        {label}
        {hint && <span className="font-normal text-muted-foreground tabular-nums">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

const STYLE_KEYS: (keyof StyleFields)[] = [
  'font', 'font_size', 'primary_color', 'highlight_color', 'outline_color', 'outline_px', 'shadow_px', 'uppercase',
  'words_per_line', 'position_y', 'animation',
]

function PresetChip({ s, active, onClick }: { s: CaptionStyle; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex h-14 w-full flex-col items-center justify-center rounded-lg border bg-secondary px-2 text-center transition-colors hover:border-primary/60',
        active && 'border-primary ring-1 ring-primary',
      )}
    >
      <span
        style={{
          fontFamily: s.font,
          fontSize: 15,
          color: s.primary_color,
          WebkitTextStroke: s.outline_px ? `${Math.min(2, s.outline_px / 3)}px ${s.outline_color}` : undefined,
          paintOrder: 'stroke fill',
        }}
      >
        {s.uppercase ? 'OLÁ ' : 'Olá '}
        <span style={{ color: s.animation === 'none' ? s.primary_color : s.highlight_color }}>{s.uppercase ? 'MUNDO' : 'mundo'}</span>
      </span>
      <span className="mt-0.5 text-[10px] text-muted-foreground">{s.name}</span>
    </button>
  )
}

export function StylePanel() {
  const { baseStyle, style } = useEditorCtx()
  const { data: styles } = useCaptionStyles()
  const overrides = useEditor((s) => s.draft?.style ?? {})
  const setDraft = useEditor((s) => s.set)
  const checkpoint = useEditor((s) => s.checkpoint)
  const create = useCreateStyle()
  const del = useDeleteStyle()
  const [saveOpen, setSaveOpen] = useState(false)
  const [name, setName] = useState('')

  const setStyle = (patch: Partial<StyleFields>, key?: string) => setDraft({ style: { ...overrides, ...patch } }, key)
  const customized = Object.keys(overrides).length > 0

  const slider = (k: 'font_size' | 'outline_px' | 'shadow_px' | 'position_y', min: number, max: number, stepV: number) => (
    <input
      type="range"
      min={min}
      max={max}
      step={stepV}
      value={style[k]}
      onPointerDown={checkpoint}
      onChange={(e) => setStyle({ [k]: Number(e.target.value) }, 'gesture')}
      className="w-full accent-primary"
    />
  )
  const color = (k: 'primary_color' | 'highlight_color' | 'outline_color', label: string) => (
    <label className="flex flex-col items-center gap-1 text-[11px] text-muted-foreground">
      <input
        type="color"
        value={style[k]}
        onChange={(e) => setStyle({ [k]: e.target.value.toUpperCase() }, k)}
        className="h-8 w-12 cursor-pointer rounded border bg-transparent"
      />
      {label}
    </label>
  )

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        {styles?.map((s) => (
          <div key={s.id} className="group relative">
            <PresetChip s={s} active={s.id === baseStyle?.id && !customized} onClick={() => setDraft({ caption_style_id: s.id, style: {} })} />
            {!s.is_builtin && (
              <button
                className="absolute top-1 right-1 hidden rounded bg-black/60 p-0.5 text-white group-hover:block"
                aria-label={`Apagar preset ${s.name}`}
                onClick={() => window.confirm(`Apagar o preset “${s.name}”?`) && del.mutate(s.id)}
              >
                <Trash2 className="size-3" />
              </button>
            )}
          </div>
        ))}
      </div>
      {customized && (
        <div className="flex items-center justify-between rounded-md bg-muted/50 px-2 py-1.5 text-xs">
          <span>
            {baseStyle?.name} <Badge variant="secondary">ajustado</Badge>
          </span>
          <Button size="sm" variant="ghost" className="h-7" onClick={() => setDraft({ style: {} })}>
            Voltar ao preset
          </Button>
        </div>
      )}

      <Row label="Fonte">
        <NativeSelect value={style.font} onChange={(e) => setStyle({ font: e.target.value })}>
          {FONTS.map((f) => (
            <option key={f.family} value={f.family}>
              {f.label}
            </option>
          ))}
        </NativeSelect>
      </Row>
      <Row label="Tamanho" hint={`${style.font_size}`}>
        {slider('font_size', 40, 160, 2)}
      </Row>
      <div className="flex justify-between">
        {color('primary_color', 'Texto')}
        {color('highlight_color', 'Destaque')}
        {color('outline_color', 'Contorno')}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Row label="Contorno" hint={`${style.outline_px}px`}>
          {slider('outline_px', 0, 14, 1)}
        </Row>
        <Row label="Sombra" hint={`${style.shadow_px}px`}>
          {slider('shadow_px', 0, 10, 1)}
        </Row>
      </div>
      <Row label="Posição vertical" hint={`${Math.round(style.position_y * 100)}%`}>
        {slider('position_y', 0.1, 0.92, 0.01)}
      </Row>
      <div className="grid grid-cols-2 gap-3">
        <Row label="Palavras por linha">
          <NativeSelect value={style.words_per_line} onChange={(e) => setStyle({ words_per_line: Number(e.target.value) })}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </NativeSelect>
        </Row>
        <Row label="Animação">
          <NativeSelect value={style.animation} onChange={(e) => setStyle({ animation: e.target.value as StyleFields['animation'] })}>
            <option value="highlight">Destaque</option>
            <option value="pop">Pop</option>
            <option value="karaoke">Karaokê</option>
            <option value="none">Nenhuma</option>
          </NativeSelect>
        </Row>
      </div>
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <Checkbox checked={style.uppercase} onChange={(e) => setStyle({ uppercase: e.target.checked })} />
        Maiúsculas
      </label>
      <Button variant="outline" size="sm" className="w-full" onClick={() => (setName(''), setSaveOpen(true))}>
        <Save /> Salvar como novo preset
      </Button>
      <Dialog open={saveOpen} onClose={() => setSaveOpen(false)} title="Salvar como novo preset">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            const body = Object.fromEntries(STYLE_KEYS.map((k) => [k, style[k]])) as unknown as StyleFields
            create.mutate(
              { ...body, name: name.trim() },
              {
                onSuccess: (s) => {
                  setDraft({ caption_style_id: s.id, style: {} })
                  setSaveOpen(false)
                  toast.success(`Preset "${s.name}" criado`)
                },
                onError: (err) => toast.error(err.message),
              },
            )
          }}
        >
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Podcast amarelo…" maxLength={60} />
          <div className="flex justify-end">
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              Salvar
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}

const MODES: { v: 'auto' | 'speaker' | 'gameplay' | 'center' | 'blur_fit' | 'split' | 'manual'; label: string; hint: string }[] = [
  { v: 'auto', label: 'Seguir rosto', hint: 'Acompanha o rosto principal de cada cena; salta seco na troca de câmera.' },
  { v: 'speaker', label: 'Quem fala no centro', hint: 'Podcast: lê os lábios e põe no centro quem está falando; troca com corte seco.' },
  { v: 'gameplay', label: 'Webcam + jogo', hint: 'Gameplay: webcam do streamer em cima, jogo centralizado embaixo.' },
  { v: 'center', label: 'Centro', hint: 'Crop fixo no meio do quadro.' },
  { v: 'blur_fit', label: 'Inteiro + fundo borrado', hint: 'Vídeo inteiro no meio; bom para tela, gameplay e slides.' },
  { v: 'split', label: 'Tela dividida', hint: 'Duas pessoas: esquerda em cima, direita embaixo. Com uma só no quadro, ela ocupa a tela toda.' },
  { v: 'manual', label: 'Manual', hint: 'Você define a posição com keyframes.' },
]

export function FramingPanel() {
  const { videoRef, track, clip } = useEditorCtx()
  const mode = useEditor((s) => s.draft?.reframe_mode ?? 'auto')
  const keyframes = useEditor((s) => s.draft?.keyframes ?? [])
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const end = useEditor((s) => s.draft?.end_s ?? 0)
  const liveX = useEditor((s) => s.liveX)
  const setDraft = useEditor((s) => s.set)
  const setLiveX = useEditor((s) => s.setLiveX)

  const rel = () => Math.min(end - start, Math.max(0, (videoRef.current?.currentTime ?? start) - start))
  const currentCx = (t: number) => {
    if (liveX !== null) return liveX
    if (mode === 'manual') return manualCx(keyframes, t)
    if (track && (mode === 'auto' || mode === 'split' || mode === 'speaker')) {
      const l = trackAt(track, t)
      return l.kind === 'single' ? l.cx : l.kind === 'split' ? (l.a[0] + l.b[0]) / 2 : 0.5
    }
    return 0.5
  }

  const choose = (v: (typeof MODES)[number]['v']) => {
    setLiveX(null)
    if (v === 'manual' && !keyframes.length) {
      // começa do enquadramento atual, para não "pular" ao trocar de modo
      setDraft({ reframe_mode: v, keyframes: [{ t: 0, x: Math.round(currentCx(rel()) * 1000) / 1000 }] })
    } else setDraft({ reframe_mode: v })
  }

  const addKeyframe = () => {
    const t = Math.round(rel() * 100) / 100
    const x = Math.round(currentCx(t) * 1000) / 1000
    const rest = keyframes.filter((k) => Math.abs(k.t - t) > 0.05)
    setDraft({ keyframes: [...rest, { t, x }].sort((a, b) => a.t - b.t) })
    setLiveX(null)
  }

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {MODES.map((m) => (
          <label
            key={m.v}
            className={cn('flex cursor-pointer gap-2 rounded-lg border p-2.5 text-sm hover:bg-accent/40', mode === m.v && 'border-primary bg-primary/5')}
          >
            <input type="radio" name="mode" className="mt-0.5 accent-primary" checked={mode === m.v} onChange={() => choose(m.v)} />
            <span>
              <span className="font-medium">{m.label}</span>
              <span className="block text-xs text-muted-foreground">{m.hint}</span>
            </span>
          </label>
        ))}
      </div>
      {mode === 'gameplay' && <GameplayControls />}
      {(mode === 'auto' || mode === 'split' || mode === 'speaker' || mode === 'gameplay') && track === null && (
        <p className="text-xs text-warning">A análise de rostos deste projeto ainda está rodando; o preview usa o centro até ela terminar.</p>
      )}
      {mode === 'manual' && (
        <div className="space-y-2 rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Arraste o retângulo no vídeo-fonte e adicione um keyframe no tempo atual. Entre keyframes o movimento é suave.</p>
          <Button size="sm" className="w-full" onClick={addKeyframe}>
            <Plus /> Adicionar keyframe {liveX !== null && '(posição arrastada)'}
          </Button>
          <ul className="divide-y text-sm">
            {keyframes.map((k, i) => (
              <li key={`${k.t}-${i}`} className="flex items-center gap-2 py-1.5">
                <button className="font-mono text-xs text-primary hover:underline" onClick={() => videoRef.current && (videoRef.current.currentTime = start + k.t)}>
                  {formatTime(k.t)}
                </button>
                <span className="text-xs text-muted-foreground">posição {(k.x * 100).toFixed(0)}%</span>
                <Button
                  size="icon"
                  variant="ghost"
                  className="ml-auto size-7"
                  aria-label="Remover keyframe"
                  onClick={() => setDraft({ keyframes: keyframes.filter((_x, j) => j !== i) })}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {clip.reframe_mode !== mode && <p className="text-xs text-muted-foreground">Salvando…</p>}
    </div>
  )
}

function GameplayControls() {
  const { track } = useEditorCtx()
  const layout = useEditor((s) => s.draft?.layout ?? {})
  const setDraft = useEditor((s) => s.set)
  const checkpoint = useEditor((s) => s.checkpoint)
  const detected = !!track?.gameplay?.cam_face
  const manualCam = !!layout.cam_center
  const set = (patch: Partial<typeof layout>, key?: string) => setDraft({ layout: { ...layout, ...patch } }, key)
  const camW = layout.cam_w ?? track?.gameplay?.cam?.[2] ?? 0.3
  return (
    <div className="space-y-3 rounded-lg border p-3 text-sm">
      <p className="text-xs text-muted-foreground">
        {detected
          ? manualCam
            ? 'Webcam posicionada por você.'
            : 'Webcam detectada automaticamente. Arraste o retângulo azul no vídeo para ajustar.'
          : manualCam
            ? 'Webcam posicionada por você (não foi detectada automaticamente).'
            : 'Não achei uma webcam fixa neste vídeo: o jogo aparece inteiro. Se houver webcam, posicione-a:'}
      </p>
      {!detected && !manualCam && (
        <Button size="sm" variant="outline" className="w-full" onClick={() => set({ cam_center: [0.85, 0.2], cam_w: 0.25 })}>
          Posicionar webcam manualmente
        </Button>
      )}
      <label className="block space-y-1">
        <span className="flex justify-between text-xs font-medium">
          Altura da webcam no vídeo <span className="font-normal text-muted-foreground">{Math.round((layout.top_ratio ?? GAMEPLAY_TOP_RATIO) * 100)}%</span>
        </span>
        <input
          type="range" min={0.25} max={0.6} step={0.01} value={layout.top_ratio ?? GAMEPLAY_TOP_RATIO}
          onPointerDown={checkpoint} onChange={(e) => set({ top_ratio: Number(e.target.value) }, 'gesture')}
          className="w-full accent-primary"
        />
      </label>
      {(detected || manualCam) && (
        <label className="block space-y-1">
          <span className="flex justify-between text-xs font-medium">
            Zoom na webcam <span className="font-normal text-muted-foreground">{Math.round((0.3 / camW) * 100)}%</span>
          </span>
          <input
            type="range" min={0.08} max={0.6} step={0.005} value={0.68 - camW}
            onPointerDown={checkpoint}
            onChange={(e) => set({ cam_w: Math.round((0.68 - Number(e.target.value)) * 1000) / 1000,
              cam_center: layout.cam_center ?? (track?.gameplay?.cam ? [track.gameplay.cam[0] + track.gameplay.cam[2] / 2, track.gameplay.cam[1] + track.gameplay.cam[3] / 2] : [0.85, 0.2]) }, 'gesture')}
            className="w-full accent-primary"
          />
        </label>
      )}
      <div className="flex flex-wrap gap-1">
        {manualCam && detected && (
          <Button size="sm" variant="ghost" onClick={() => set({ cam_center: undefined, cam_w: undefined })}>
            Usar a webcam detectada
          </Button>
        )}
        {layout.game_cx !== undefined && layout.game_cx !== 0.5 && (
          <Button size="sm" variant="ghost" onClick={() => set({ game_cx: 0.5 })}>
            Centralizar o jogo
          </Button>
        )}
      </div>
    </div>
  )
}

export function TextPanel() {
  const titleOverlay = useEditor((s) => s.draft?.title_overlay ?? '')
  const titleUntil = useEditor((s) => s.draft?.title_until ?? null)
  const title = useEditor((s) => s.draft?.title ?? '')
  const setDraft = useEditor((s) => s.set)
  return (
    <div className="space-y-4">
      <Row label="Título fixo no topo do vídeo">
        <Input value={titleOverlay} onChange={(e) => setDraft({ title_overlay: e.target.value }, 'title_overlay')}  maxLength={120} />
      </Row>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={!title} onClick={() => setDraft({ title_overlay: title })}>
          Usar o título do corte
        </Button>
        {titleOverlay && (
          <Button size="sm" variant="ghost" onClick={() => setDraft({ title_overlay: '' })}>
            Remover
          </Button>
        )}
      </div>
      <label className={cn('flex cursor-pointer items-center gap-2 text-sm', !titleOverlay && 'opacity-50')}>
        <Checkbox checked={titleUntil !== null} disabled={!titleOverlay} onChange={(e) => setDraft({ title_until: e.target.checked ? 3 : null })} />
        Mostrar só nos 3 primeiros segundos
      </label>
      <p className="text-xs text-muted-foreground">O título aparece numa caixa branca no topo, acima da área que as redes cobrem com botões.</p>
    </div>
  )
}

export function ExportPanel({ onRender }: { onRender: () => void }) {
  const { clip } = useEditorCtx()
  const quality = useEditor((s) => s.draft?.quality ?? 'normal')
  const normalize = useEditor((s) => s.draft?.normalize_audio ?? null)
  const setDraft = useEditor((s) => s.set)
  const { data: jobs } = useJobs()
  const { cancel } = useJobActions()
  const { render } = useClipActions(clip.project_id)
  const job = jobs?.find((j) => j.type === 'render' && j.ref_id === clip.id && (j.status === 'queued' || j.status === 'running'))
  const [watch, setWatch] = useState(false)

  return (
    <div className="space-y-4">
      <Row label="Qualidade">
        <NativeSelect value={quality} onChange={(e) => setDraft({ quality: e.target.value as 'high' | 'normal' | 'small' })}>
          <option value="high">Alta (até 12 Mbps)</option>
          <option value="normal">Normal (até 8 Mbps)</option>
          <option value="small">Arquivo pequeno (até 4 Mbps)</option>
        </NativeSelect>
      </Row>
      <label className="flex cursor-pointer items-center gap-2 text-sm">
        <Checkbox checked={normalize ?? true} onChange={(e) => setDraft({ normalize_audio: e.target.checked })} />
        Normalizar áudio (−14 LUFS, padrão das redes)
      </label>
      {job ? (
        <div className="space-y-2 rounded-lg border p-3 text-sm">
          <div className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin text-primary" />
            {job.status === 'queued' ? 'Na fila…' : job.message}
            <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => cancel.mutate(job.id)}>
              <Ban /> Cancelar
            </Button>
          </div>
          {job.status === 'running' && <Progress value={job.progress} />}
        </div>
      ) : (
        <Button className="w-full" onClick={onRender} disabled={render.isPending}>
          <Play /> Renderizar <kbd className="ml-auto text-[10px] opacity-70">Ctrl+Enter</kbd>
        </Button>
      )}
      {clip.status === 'error' && clip.error && <p className="text-xs text-destructive">Último render falhou: {clip.error}</p>}
      {clip.output_path && !job && (
        <div className="space-y-2 rounded-lg border p-3">
          <div className={cn('text-xs', clip.status === 'rendered' ? 'text-success' : 'text-warning')}>
            {clip.status === 'rendered' ? 'MP4 pronto' : 'MP4 desatualizado (há edições depois do último render)'}
          </div>
          <div className="truncate font-mono text-[11px] text-muted-foreground" title={clip.output_path}>
            {clip.output_path.split('/').pop()}
          </div>
          <div className="flex flex-wrap gap-1">
            <Button size="sm" variant="outline" onClick={() => setWatch(true)}>
              <Play /> Assistir
            </Button>
            <Button size="sm" variant="outline" asChild>
              <a href={clipFileUrl(clip.id, true)} download>
                <Download /> Baixar
              </a>
            </Button>
            <Button size="sm" variant="ghost" onClick={() => openFolder(clip.output_path).catch((e: Error) => toast.error(e.message))}>
              <FolderOpen /> Pasta
            </Button>
          </div>
        </div>
      )}
      <Dialog open={watch} onClose={() => setWatch(false)} title={clip.title} className="max-w-sm">
        <video src={`${clipFileUrl(clip.id)}?v=${encodeURIComponent(clip.rendered_at ?? '')}`} controls autoPlay playsInline className="aspect-[9/16] w-full rounded-lg bg-black" />
      </Dialog>
    </div>
  )
}

