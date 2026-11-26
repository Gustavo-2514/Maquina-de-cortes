import { ArrowLeft, Check, Cloud, Keyboard, Loader2, Pause, Play, Redo2, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { api } from '@/api/client'
import { clipsKey, useClipActions } from '@/api/clips'
import { useCaptionStyles, useClip, useCropTrack } from '@/api/editor'
import { parseOptions, usePrepareMedia, useProject, useProjectFiles, useTranscript } from '@/api/projects'
import type { Clip } from '@/api/types'
import { ClipTranscript } from '@/editor/ClipTranscript'
import { EditorContext, type EditorCtx, useEditorCtx, useVideoTime } from '@/editor/context'
import { ExportPanel, FramingPanel, StylePanel, TextPanel } from '@/editor/panels'
import { Preview } from '@/editor/Preview'
import { SourceView } from '@/editor/SourceView'
import { Timeline } from '@/editor/Timeline'
import { formatTime, scoreVariant } from '@/lib/clip'
import { registerFonts } from '@/lib/fonts'
import { cn } from '@/lib/utils'
import { useQueryClient } from '@tanstack/react-query'
import { type StyleFields, patchDiff, useEditor } from '@/stores/editor'

const AUTOSAVE_MS = 800

type Tab = 'legenda' | 'enquadramento' | 'texto' | 'exportar'
const TABS: { k: Tab; label: string }[] = [
  { k: 'legenda', label: 'Legenda' },
  { k: 'enquadramento', label: 'Enquadrar' },
  { k: 'texto', label: 'Título' },
  { k: 'exportar', label: 'Exportar' },
]

const SHORTCUTS: [string, string][] = [
  ['Espaço', 'tocar / pausar'],
  ['J / K / L', 'voltar 2 s / pausar / tocar (L de novo = 2×)'],
  ['← / →', '1 frame (Shift = 1 s)'],
  ['I / O', 'início / fim do corte no playhead'],
  ['Ctrl+Z / Ctrl+Shift+Z', 'desfazer / refazer'],
  ['Ctrl+S', 'salvar agora'],
  ['Ctrl+Enter', 'renderizar'],
]

/** Salva o rascunho com debounce; devolve flush() para salvar já (Ctrl+S / antes de renderizar). */
function useAutosave(clip: Clip | undefined) {
  const qc = useQueryClient()
  const draft = useEditor((s) => s.draft)
  const saved = useEditor((s) => s.saved)
  const markSaved = useEditor((s) => s.markSaved)
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle')
  const inflight = useRef<Promise<void> | null>(null)

  const save = useCallback(async () => {
    const { draft: d, saved: sv, clipId } = useEditor.getState()
    if (!d || clipId === null) return
    const diff = patchDiff(sv, d)
    if (!Object.keys(diff).length) return
    setState('saving')
    try {
      const c = await api<Clip>(`/clips/${clipId}`, { method: 'PATCH', body: JSON.stringify(diff) })
      markSaved(d)
      qc.setQueryData(['clip', c.id], c)
      qc.setQueryData<Clip[]>(clipsKey(c.project_id), (old) => old?.map((x) => (x.id === c.id ? c : x)))
      setState('idle') // edições feitas durante o PATCH continuam "Alterado" (derivado do diff)
    } catch (e) {
      setState('error')
      toast.error(`Não foi possível salvar: ${e instanceof Error ? e.message : e}`)
    }
  }, [markSaved, qc])

  const flush = useCallback(async () => {
    if (inflight.current) await inflight.current
    inflight.current = save()
    await inflight.current
    inflight.current = null
  }, [save])

  useEffect(() => {
    if (!draft || !clip) return
    if (!Object.keys(patchDiff(saved, draft)).length) return
    const id = setTimeout(() => void flush(), AUTOSAVE_MS)
    return () => clearTimeout(id)
  }, [draft, saved, clip, flush])

  // salva ao sair da página
  useEffect(() => () => void flush(), [flush])
  const dirty = !!draft && Object.keys(patchDiff(saved, draft)).length > 0
  return { state: state === 'idle' ? (dirty ? 'pending' : 'saved') : state, flush }
}

function PlayButton({ onToggle }: { onToggle: () => void }) {
  const t = useVideoTime(10)
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const [paused, setPaused] = useState(true)
  const { videoRef } = useEditorCtx()
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const on = () => setPaused(v.paused)
    v.addEventListener('play', on)
    v.addEventListener('pause', on)
    return () => {
      v.removeEventListener('play', on)
      v.removeEventListener('pause', on)
    }
  }, [videoRef])
  return (
    <div className="flex items-center gap-2">
      <Button size="icon" onClick={onToggle} aria-label={paused ? 'Tocar' : 'Pausar'}>
        {paused ? <Play /> : <Pause />}
      </Button>
      <span className="font-mono text-xs text-muted-foreground tabular-nums">
        {formatTime(t)} <span className="opacity-60">({formatTime(Math.max(0, t - start))} no corte)</span>
      </span>
    </div>
  )
}

export default function EditorPage() {
  const clipId = Number(useParams().clipId)
  const { data: clip, isLoading, error } = useClip(clipId)
  const { data: project } = useProject(clip?.project_id ?? NaN)
  const { data: transcript } = useTranscript(clip?.project_id ?? NaN, !!clip)
  const { data: styles } = useCaptionStyles()
  const load = useEditor((s) => s.load)
  const draft = useEditor((s) => s.draft)
  const loadedId = useEditor((s) => s.clipId)
  const undo = useEditor((s) => s.undo)
  const redo = useEditor((s) => s.redo)
  const canUndo = useEditor((s) => s.past.length > 0)
  const canRedo = useEditor((s) => s.future.length > 0)
  const setDraft = useEditor((s) => s.set)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [tab, setTab] = useState<Tab>('legenda')
  const [helpOpen, setHelpOpen] = useState(false)
  const { state: saveState, flush } = useAutosave(clip)
  const { render } = useClipActions(clip?.project_id ?? 0)
  const { data: files } = useProjectFiles(clip?.project_id ?? NaN, !!clip)
  const prepare = usePrepareMedia(clip?.project_id ?? NaN)

  useEffect(() => registerFonts(), [])
  // carrega o rascunho uma vez por corte (atualizações do servidor depois disso não sobrescrevem edições)
  useEffect(() => {
    if (clip && loadedId !== clip.id) load(clip)
  }, [clip, loadedId, load])

  // trilha do servidor para o que já está salvo (auto/split); o preview mantém a anterior enquanto recalcula
  const signature = clip ? `${clip.start_s}|${clip.end_s}|${clip.reframe_mode}|${clip.manual_crop_json}` : ''
  const needsTrack = !!clip && (draft?.reframe_mode === 'auto' || draft?.reframe_mode === 'split')
  const { data: track, isPlaceholderData } = useCropTrack(clipId, signature, needsTrack && clip.reframe_mode === draft?.reframe_mode)

  const words = useMemo(() => transcript?.segments.flatMap((s) => s.words.map((w) => ({ w: w.w, s: w.s, e: w.e }))) ?? [], [transcript])
  const styleId = draft?.caption_style_id ?? null
  const baseStyle = useMemo(() => {
    if (!styles?.length) return undefined
    const byId = styleId != null ? styles.find((s) => s.id === styleId) : undefined
    const key = project ? parseOptions(project).caption_style : 'hormozi'
    return byId ?? styles.find((s) => s.key === key) ?? styles.find((s) => s.key === 'hormozi') ?? styles[0]
  }, [styles, styleId, project])
  const styleOverrides = draft?.style
  const style: StyleFields | null = useMemo(
    () => (baseStyle ? ({ ...baseStyle, ...(styleOverrides ?? {}) } as StyleFields) : null),
    [baseStyle, styleOverrides],
  )

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    const d = useEditor.getState().draft
    if (!v || !d) return
    if (v.paused) {
      if (v.currentTime >= d.end_s - 0.05 || v.currentTime < d.start_s - 0.5) v.currentTime = d.start_s
      v.playbackRate = 1
      void v.play()
    } else v.pause()
  }, [])

  // para no fim do corte quando a reprodução começou dentro dele
  useEffect(() => {
    let raf = 0
    let wasInside = false
    const loop = () => {
      const v = videoRef.current
      const d = useEditor.getState().draft
      if (v && d && !v.paused) {
        if (v.currentTime >= d.start_s - 0.05 && v.currentTime < d.end_s) wasInside = true
        else if (wasInside && v.currentTime >= d.end_s) {
          v.pause()
          v.currentTime = d.end_s
          wasInside = false
        }
      } else wasInside = false
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const doRender = useCallback(async () => {
    if (!clip) return
    await flush()
    render.mutate(clip.id, {
      onSuccess: () => toast.success('Render na fila'),
      onError: (e) => toast.error(e.message),
    })
    setTab('exportar')
  }, [clip, flush, render])

  // atalhos
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('input, textarea, select, [contenteditable=true]')) return
      const v = videoRef.current
      const d = useEditor.getState().draft
      if (!v || !d) return
      const ctrl = e.ctrlKey || e.metaKey
      const frame = 1 / (project?.fps || 30)
      if (ctrl && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
      } else if (ctrl && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        redo()
      } else if (ctrl && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void flush().then(() => toast.success('Salvo'))
      } else if (ctrl && e.key === 'Enter') {
        e.preventDefault()
        void doRender()
      } else if (ctrl) return
      else if (e.key === ' ') {
        e.preventDefault()
        togglePlay()
      } else if (e.key === 'k' || e.key === 'K') v.pause()
      else if (e.key === 'l' || e.key === 'L') {
        if (!v.paused) v.playbackRate = v.playbackRate >= 2 ? 1 : 2
        else {
          v.playbackRate = 1
          void v.play()
        }
      } else if (e.key === 'j' || e.key === 'J') v.currentTime = Math.max(0, v.currentTime - 2)
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        v.pause()
        const dt = (e.shiftKey ? 1 : frame) * (e.key === 'ArrowLeft' ? -1 : 1)
        v.currentTime = Math.max(0, v.currentTime + dt)
      } else if (e.key === 'i' || e.key === 'I') {
        if (d.end_s - v.currentTime >= 1) setDraft({ start_s: Math.round(v.currentTime * 1000) / 1000 })
        else toast.error('O início precisa ficar pelo menos 1 s antes do fim')
      } else if (e.key === 'o' || e.key === 'O') {
        if (v.currentTime - d.start_s >= 1) setDraft({ end_s: Math.round(v.currentTime * 1000) / 1000 })
        else toast.error('O fim precisa ficar pelo menos 1 s depois do início')
      } else if (e.key === '?') setHelpOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [project?.fps, undo, redo, flush, doRender, togglePlay, setDraft])

  if (isLoading) return <p className="p-8 text-sm text-muted-foreground">Carregando…</p>
  if (error || (clip === undefined && !isLoading))
    return (
      <div className="p-8 text-sm">
        <p className="text-destructive">Corte não encontrado.</p>
        <Link to="/projetos" className="text-primary underline">
          Voltar aos projetos
        </Link>
      </div>
    )
  if (!clip || !project || !draft || loadedId !== clip.id || !style)
    return <p className="p-8 text-sm text-muted-foreground">Carregando editor…</p>
  if (!project.width || project.stage === 'probe' || project.stage === 'proxy')
    return <p className="p-8 text-sm text-muted-foreground">O vídeo deste projeto está sendo preparado… a página abre sozinha quando terminar.</p>
  if (files && !files.proxy)
    return (
      <div className="m-8 max-w-xl space-y-3 rounded-xl border p-6 text-sm">
        <p>O vídeo de edição deste projeto foi apagado na limpeza de disco. Os cortes e a transcrição continuam salvos.</p>
        <Button onClick={() => prepare.mutate(undefined, { onError: (e) => toast.error(e.message) })} disabled={prepare.isPending || project.status === 'processing'}>
          {prepare.isPending || project.status === 'processing' ? <Loader2 className="animate-spin" /> : <Play />} Preparar de novo (rápido)
        </Button>
      </div>
    )

  const ctx: EditorCtx = {
    videoRef,
    project,
    clip,
    words,
    track: needsTrack ? (track as EditorCtx['track']) : undefined,
    trackStale: isPlaceholderData || clip.reframe_mode !== draft.reframe_mode || `${clip.start_s}|${clip.end_s}` !== `${draft.start_s}|${draft.end_s}`,
    baseStyle,
    style,
    fps: project.fps || 30,
  }

  return (
    <EditorContext.Provider value={ctx}>
      <div className="flex min-h-full flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b px-6 py-3">
          <Button variant="ghost" size="icon" asChild>
            <Link to={`/projetos/${project.id}`} aria-label="Voltar ao projeto" onClick={() => void flush()}>
              <ArrowLeft />
            </Link>
          </Button>
          <input
            value={draft.title}
            onChange={(e) => setDraft({ title: e.target.value }, 'title')}
            placeholder="Título do corte…"
            maxLength={200}
            className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-lg font-semibold outline-none hover:border-input focus:border-ring"
          />
          {clip.origin === 'ai' && (
            <span className={cn('rounded-md border px-2 py-0.5 text-sm font-semibold tabular-nums', scoreVariant(clip.score))} title="Nota de potencial viral">
              Nota {Math.round(clip.score)}
            </span>
          )}
          <span className="flex w-24 items-center gap-1 text-xs text-muted-foreground">
            {saveState === 'saving' ? (
              <>
                <Loader2 className="size-3.5 animate-spin" /> Salvando…
              </>
            ) : saveState === 'pending' ? (
              <>
                <Cloud className="size-3.5" /> Alterado
              </>
            ) : saveState === 'error' ? (
              <span className="text-destructive">Erro ao salvar</span>
            ) : (
              <>
                <Check className="size-3.5 text-success" /> Salvo
              </>
            )}
          </span>
          <Button variant="ghost" size="icon" disabled={!canUndo} onClick={undo} aria-label="Desfazer (Ctrl+Z)" title="Desfazer (Ctrl+Z)">
            <Undo2 />
          </Button>
          <Button variant="ghost" size="icon" disabled={!canRedo} onClick={redo} aria-label="Refazer (Ctrl+Shift+Z)" title="Refazer (Ctrl+Shift+Z)">
            <Redo2 />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setHelpOpen(true)} aria-label="Atalhos de teclado" title="Atalhos (?)">
            <Keyboard />
          </Button>
          <Button onClick={() => void doRender()} disabled={render.isPending}>
            <Play /> Renderizar
          </Button>
        </header>

        <div className="grid flex-1 gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_auto_340px]">
          <div className="min-w-0 space-y-3">
            <SourceView />
            <PlayButton onToggle={togglePlay} />
            <ClipTranscript />
          </div>
          <Preview />
          <Card className="h-fit gap-0 py-0">
            <div className="grid grid-cols-4 border-b">
              {TABS.map((t) => (
                <button
                  key={t.k}
                  onClick={() => setTab(t.k)}
                  className={cn(
                    'border-b-2 border-transparent px-1 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground',
                    tab === t.k && 'border-primary text-foreground',
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="max-h-[calc(100dvh-220px)] overflow-y-auto p-4">
              {tab === 'legenda' && <StylePanel />}
              {tab === 'enquadramento' && <FramingPanel />}
              {tab === 'texto' && <TextPanel />}
              {tab === 'exportar' && <ExportPanel onRender={() => void doRender()} />}
            </div>
          </Card>
        </div>

        <div className="border-t px-5 py-4">
          <Timeline />
        </div>
      </div>

      <Dialog open={helpOpen} onClose={() => setHelpOpen(false)} title="Atalhos do editor">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          {SHORTCUTS.map(([k, d]) => (
            <div key={k} className="contents">
              <dt>
                <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd>
              </dt>
              <dd className="text-muted-foreground">{d}</dd>
            </div>
          ))}
        </dl>
      </Dialog>
    </EditorContext.Provider>
  )
}
