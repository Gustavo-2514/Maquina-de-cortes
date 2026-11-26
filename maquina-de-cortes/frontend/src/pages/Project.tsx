import { AlertTriangle, ArrowLeft, Ban, Pencil, RotateCcw, Sparkles, Trash2 } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { AnalysisDialog } from '@/components/AnalysisDialog'
import { ClipsPanel } from '@/components/ClipsPanel'
import { LANGUAGES } from '@/lib/languages'
import { ProjectStatusBadge, ProjectSteps } from '@/components/ProjectProgress'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useJobActions, useJobs } from '@/api/jobs'
import { mediaUrl, usePrepareMedia, useProject, useProjectActions, useProjectFiles, useTranscript } from '@/api/projects'
import type { Clip, Project, Transcript } from '@/api/types'
import { type FlatWord, wordAt } from '@/lib/transcript'
import { formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Transcrição clicável
// ---------------------------------------------------------------------------

const WordSpan = memo(function WordSpan({
  word,
  active,
  inClip,
  onSeek,
  onEdit,
}: {
  word: FlatWord
  active: boolean
  inClip: boolean
  onSeek: (t: number) => void
  onEdit: (w: FlatWord) => void
}) {
  return (
    <span
      data-active={active || undefined}
      onClick={() => onSeek(word.s)}
      onDoubleClick={() => onEdit(word)}
      title={`${formatDuration(word.s)} · confiança ${(word.p * 100).toFixed(0)}% · duplo clique para corrigir`}
      className={cn(
        'cursor-pointer rounded px-0.5 transition-colors hover:bg-accent',
        word.p < 0.5 && 'underline decoration-warning/60 decoration-dotted underline-offset-4',
        inClip && 'bg-primary/15',
        active && 'bg-primary text-primary-foreground hover:bg-primary',
      )}
    >
      {word.w}
    </span>
  )
})

function TranscriptView({
  projectId,
  transcript,
  currentTime,
  onSeek,
  clipRange,
}: {
  projectId: number
  transcript: Transcript
  currentTime: number
  onSeek: (t: number) => void
  clipRange: [number, number] | null
}) {
  const { saveTranscript } = useProjectActions()
  const [editing, setEditing] = useState<FlatWord | null>(null)
  const [draft, setDraft] = useState('')
  const [follow, setFollow] = useState(true)
  const boxRef = useRef<HTMLDivElement>(null)

  const flat = useMemo(
    () => transcript.segments.flatMap((seg, si) => seg.words.map((w, idx) => ({ ...w, seg: si, idx }))),
    [transcript],
  )
  const offsets = useMemo(() => {
    const out: number[] = []
    let acc = 0
    for (const seg of transcript.segments) {
      out.push(acc)
      acc += seg.words.length
    }
    return out
  }, [transcript])
  const active = wordAt(flat, currentTime)

  // rola para manter a palavra atual visível
  useEffect(() => {
    if (!follow || active < 0) return
    const el = boxRef.current?.querySelector('[data-active]') as HTMLElement | null
    const box = boxRef.current
    if (!el || !box) return
    const top = el.offsetTop - box.offsetTop
    if (top < box.scrollTop + 40 || top > box.scrollTop + box.clientHeight - 60) box.scrollTo({ top: top - box.clientHeight / 3, behavior: 'smooth' })
  }, [active, follow])

  const startEdit = useCallback((w: FlatWord) => {
    setEditing(w)
    setDraft(w.w)
  }, [])

  function commit() {
    if (!editing) return
    const text = draft.trim()
    const w = editing
    setEditing(null)
    if (!text || text === w.w) return
    const next: Transcript = {
      ...transcript,
      segments: transcript.segments.map((seg, si) =>
        si !== w.seg ? seg : { ...seg, words: seg.words.map((x, i) => (i === w.idx ? { ...x, w: text } : x)) },
      ),
    }
    saveTranscript.mutate(
      { id: projectId, transcript: next },
      { onSuccess: () => toast.success('Palavra corrigida'), onError: (e) => toast.error(e.message) },
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Clique numa palavra para ir até ela · duplo clique para corrigir
          {transcript.model && ` · Whisper ${transcript.model} (${transcript.device})`}
        </span>
        <label className="flex cursor-pointer items-center gap-1.5">
          <input type="checkbox" className="accent-primary" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          Acompanhar
        </label>
      </div>
      <div ref={boxRef} className="relative max-h-[60dvh] space-y-3 overflow-y-auto pr-2 text-[15px] leading-7">
        {transcript.segments.map((seg, si) => (
          <p key={seg.id} className="flex gap-3">
            <button
              onClick={() => onSeek(seg.start)}
              className="mt-0.5 h-fit shrink-0 font-mono text-xs text-muted-foreground tabular-nums hover:text-primary"
            >
              {formatDuration(seg.start)}
            </button>
            <span>
              {seg.words.map((_w, wi) => {
                const i = offsets[si] + wi
                const fw = flat[i]
                if (editing && editing.seg === fw.seg && editing.idx === fw.idx)
                  return (
                    <input
                      key={i}
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={commit}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commit()
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      style={{ width: `${Math.max(3, draft.length + 1)}ch` }}
                      className="rounded border border-primary bg-background px-0.5 outline-none"
                    />
                  )
                return (
                  <span key={i}>
                    <WordSpan
                      word={fw}
                      active={i === active}
                      inClip={!!clipRange && fw.s >= clipRange[0] - 0.05 && fw.e <= clipRange[1] + 0.05}
                      onSeek={onSeek}
                      onEdit={startEdit}
                    />{' '}
                  </span>
                )
              })}
              {seg.words.length === 0 && <span className="text-muted-foreground">{seg.text}</span>}
            </span>
          </p>
        ))}
        {transcript.segments.length === 0 && <p className="text-sm text-muted-foreground">Nenhuma fala detectada no vídeo.</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function ErrorBox({ p }: { p: Project }) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
      <div className="flex items-center gap-2 font-medium text-destructive">
        <AlertTriangle className="size-4" /> {p.error}
      </div>
      {p.error_detail && (
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer">Detalhe técnico</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all">{p.error_detail}</pre>
        </details>
      )}
    </div>
  )
}

export default function ProjectPage() {
  const id = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { data: p, isLoading, error } = useProject(id)
  const hasTranscript = !!p && (p.status === 'ready' || ['analyze', 'done'].includes(p.stage))
  const proxyReady = hasTranscript || p?.stage === 'transcribe'
  const { data: transcript, isLoading: tLoading } = useTranscript(id, hasTranscript)
  const { rename, remove } = useProjectActions()
  const { data: jobs } = useJobs()
  const { cancel } = useJobActions()
  const [configOpen, setConfigOpen] = useState(false)
  const { data: files } = useProjectFiles(id, !!p && p.status === 'ready')
  const prepare = usePrepareMedia(id)
  const [time, setTime] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [selected, setSelected] = useState<Clip | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)
  const stopAt = useRef<number | null>(null) // fim do corte que está tocando

  // aberto vindo de "Criar cortes" (?configurar=1): abre a configuração da análise
  const wantsConfig = params.get('configurar') === '1'
  const showConfig = configOpen || (wantsConfig && p?.status === 'new')
  const closeConfig = () => {
    setConfigOpen(false)
    if (wantsConfig) setParams({}, { replace: true })
  }

  // tempo do player em ~60 fps enquanto toca (timeupdate só dispara ~4×/s)
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    let raf = 0
    const tick = () => {
      setTime(v.currentTime)
      if (stopAt.current != null && v.currentTime >= stopAt.current) {
        v.pause()
        stopAt.current = null
        setPlayingId(null)
      }
      if (!v.paused) raf = requestAnimationFrame(tick)
    }
    const onPlay = () => (raf = requestAnimationFrame(tick))
    const onSeek = () => setTime(v.currentTime)
    const onPause = () => setPlayingId(null)
    v.addEventListener('play', onPlay)
    v.addEventListener('seeked', onSeek)
    v.addEventListener('pause', onPause)
    return () => {
      cancelAnimationFrame(raf)
      v.removeEventListener('play', onPlay)
      v.removeEventListener('seeked', onSeek)
      v.removeEventListener('pause', onPause)
    }
  }, [p?.id, proxyReady])

  const seek = useCallback((t: number) => {
    const v = videoRef.current
    if (!v) return
    stopAt.current = null // clique na transcrição: toca livre
    v.currentTime = t
    setTime(t)
    v.play().catch(() => {})
  }, [])

  const playClip = useCallback(
    (c: Clip) => {
      const v = videoRef.current
      if (!v) return
      if (playingId === c.id && !v.paused) {
        v.pause()
        return
      }
      setSelected(c)
      // retomar de onde parou se ainda estiver dentro do corte; senão, do início
      const t = selected?.id === c.id && v.currentTime > c.start_s && v.currentTime < c.end_s - 0.2 ? v.currentTime : c.start_s
      v.currentTime = t
      setTime(t)
      stopAt.current = c.end_s
      v.play().then(() => setPlayingId(c.id)).catch(() => {})
      v.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    },
    [playingId, selected],
  )
  const getTime = useCallback(() => videoRef.current?.currentTime ?? 0, [])

  if (isLoading) return <p className="p-8 text-sm text-muted-foreground">Carregando…</p>
  if (error || !p)
    return (
      <div className="p-8 text-sm">
        <p className="text-destructive">Projeto não encontrado.</p>
        <Link to="/projetos" className="text-primary underline">
          Voltar aos projetos
        </Link>
      </div>
    )

  const activeJobs = jobs?.filter((j) => j.ref_id === p.id && ['probe_proxy', 'transcribe', 'analyze'].includes(j.type) && ['queued', 'running'].includes(j.status)) ?? []
  const langLabel = (code: string) => LANGUAGES.find(([c]) => c === code)?.[1] ?? code

  return (
    <>
      <header className="flex flex-wrap items-center gap-3 border-b px-8 py-5">
        <Button variant="ghost" size="icon" asChild>
          <Link to="/projetos" aria-label="Voltar">
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-xl font-semibold tracking-tight" title={p.name}>
              {p.name}
            </h1>
            <button
              className="text-muted-foreground hover:text-foreground"
              aria-label="Renomear"
              onClick={() => {
                const name = window.prompt('Nome do projeto', p.name)?.trim()
                if (name && name !== p.name) rename.mutate({ id: p.id, name }, { onError: (e) => toast.error(e.message) })
              }}
            >
              <Pencil className="size-3.5" />
            </button>
            <ProjectStatusBadge p={p} />
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {[
              formatDuration(p.duration_s),
              p.width && p.height && `${p.width}×${p.height}`,
              p.fps && `${Math.round(p.fps)} fps`,
              { download: 'download', upload: 'upload', local_path: 'arquivo local' }[p.origin],
              p.detected_language && `idioma: ${langLabel(p.detected_language)}`,
              p.word_count > 0 && `${p.word_count} palavras`,
              p.faces_ready
                ? 'rostos analisados'
                : jobs?.some((j) => j.type === 'reframe' && j.ref_id === p.id && j.status === 'running')
                  ? 'analisando rostos…'
                  : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </div>
        </div>
        {activeJobs.length > 0 ? (
          <Button variant="outline" onClick={() => activeJobs.forEach((j) => cancel.mutate(j.id))}>
            <Ban /> Cancelar análise
          </Button>
        ) : (
          <Button onClick={() => setConfigOpen(true)} variant={p.status === 'new' ? 'default' : 'outline'}>
            {p.status === 'new' ? <Sparkles /> : <RotateCcw />}
            {p.status === 'new' ? 'Analisar' : p.status === 'error' ? 'Tentar de novo' : 'Reanalisar'}
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="text-muted-foreground"
          aria-label="Apagar projeto"
          onClick={() => {
            if (!window.confirm(`Apagar o projeto “${p.name}”? Os arquivos gerados (proxy, transcrição) são removidos; o vídeo original fica.`)) return
            remove.mutate(p.id, {
              onSuccess: () => (toast.success('Projeto apagado'), navigate('/projetos')),
              onError: (e) => toast.error(e.message),
            })
          }}
        >
          <Trash2 />
        </Button>
      </header>

      {p.status === 'ready' && files && !files.proxy && (
        <div className="mx-8 mt-6 flex items-center gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
          <AlertTriangle className="size-4 shrink-0 text-warning" />
          <span className="flex-1">
            O vídeo de edição deste projeto foi apagado na limpeza de disco. Prepare de novo para tocar e editar (os cortes e a transcrição continuam aqui).
          </span>
          <Button size="sm" onClick={() => prepare.mutate(undefined, { onError: (e) => toast.error(e.message) })} disabled={prepare.isPending}>
            <RotateCcw /> Preparar de novo
          </Button>
        </div>
      )}
      <div className="grid gap-6 p-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <div className="overflow-hidden rounded-xl border bg-black">
            {proxyReady && files?.proxy !== false ? (
              <video
                ref={videoRef}
                key={p.id}
                src={mediaUrl(p.id, 'proxy.mp4')}
                controls
                preload="metadata"
                className="aspect-video w-full"
              />
            ) : (
              <div className="grid aspect-video place-items-center text-sm text-muted-foreground">
                {p.status === 'new' ? 'O player aparece depois que o vídeo for preparado.' : 'Preparando o vídeo…'}
              </div>
            )}
          </div>

          <ClipsPanel
            projectId={p.id}
            duration={p.duration_s ?? 0}
            enabled={p.status === 'ready' || (p.stage === 'done' && p.status !== 'new') || p.stage === 'analyze'}
            analyzing={p.status === 'processing'}
            playingId={playingId}
            selectedId={selected?.id ?? null}
            onPlay={playClip}
            getTime={getTime}
          />
        </div>

        <div className="space-y-6">
          {(p.status !== 'ready' || p.error) && (
            <Card>
              <CardHeader>
                <CardTitle>Análise</CardTitle>
                {p.status === 'new' && (
                  <CardDescription>
                    {p.error ? `${p.error}. ` : ''}Clique em <b>Analisar</b> para preparar o vídeo e transcrever.
                  </CardDescription>
                )}
              </CardHeader>
              <CardContent className="space-y-4">
                {p.status !== 'new' && <ProjectSteps p={p} />}
                {p.status === 'error' && <ErrorBox p={p} />}
                {p.status === 'processing' && (
                  <p className="text-xs text-muted-foreground">{activeJobs.find((j) => j.status === 'running')?.message ?? 'Na fila…'}</p>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Transcrição
                {transcript && <Badge variant="secondary">{langLabel(transcript.language)}</Badge>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!hasTranscript && <p className="text-sm text-muted-foreground">A transcrição aparece aqui quando a análise terminar.</p>}
              {hasTranscript && tLoading && <p className="text-sm text-muted-foreground">Carregando transcrição…</p>}
              {transcript && (
                <TranscriptView
                  projectId={p.id}
                  transcript={transcript}
                  currentTime={time}
                  onSeek={seek}
                  clipRange={selected ? [selected.start_s, selected.end_s] : null}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {showConfig && <AnalysisDialog project={p} open onClose={closeConfig} />}
    </>
  )
}
