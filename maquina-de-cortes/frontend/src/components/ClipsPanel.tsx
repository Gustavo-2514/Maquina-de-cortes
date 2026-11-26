import { AlertTriangle, ArchiveRestore, Ban, ChevronDown, Copy, Download, Film, FolderOpen, Loader2, Package, Pause, Pencil, Play, Plus, Scissors, Send, ShieldCheck, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input, NativeSelect, Progress } from '@/components/ui/input'
import { clipFileUrl, clipPreviewUrl, exportZipUrl, parseBreakdown, REFRAME_LABELS, useApplyTemplate, useClipActions, useClips } from '@/api/clips'
import { PostPackBadge, PostPackPanel } from '@/components/PostPackPanel'
import { ReviewBadge, ReviewDetails, ReviewDialog } from '@/components/ReviewPanel'
import { parseAiCost, parseOptions, useProject } from '@/api/projects'
import { TemplatePicker } from '@/components/TemplatePicker'
import { openFolder } from '@/api/downloads'
import { useJobActions, useJobs } from '@/api/jobs'
import type { Clip, Job } from '@/api/types'
import { formatTime, parseTime, scoreVariant } from '@/lib/clip'
import { formatDuration, formatUsd } from '@/lib/format'
import { cn } from '@/lib/utils'

function ScoreBadge({ c }: { c: Clip }) {
  if (c.origin === 'manual' && c.score === 0)
    return <span className="grid h-10 w-12 shrink-0 place-items-center rounded-md border text-[10px] text-muted-foreground uppercase">manual</span>
  return (
    <span className={cn('grid h-10 w-12 shrink-0 place-items-center rounded-md border text-lg font-semibold tabular-nums', scoreVariant(c.score))}>
      {Math.round(c.score)}
    </span>
  )
}

const BREAKDOWN_LABELS: [keyof ReturnType<typeof parseBreakdown>, string, number][] = [
  ['gancho', 'Gancho', 10],
  ['emocao', 'Emoção', 10],
  ['clareza', 'Clareza', 10],
  ['completude', 'Completude', 10],
  ['energia', 'Energia do áudio', 100],
  ['ritmo', 'Ritmo de fala', 100],
  ['silencio', 'Poucos silêncios', 100],
]

function Breakdown({ c }: { c: Clip }) {
  const b = parseBreakdown(c)
  const rows = BREAKDOWN_LABELS.filter(([k]) => b[k] != null)
  if (!rows.length) return null
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-4">
      {rows.map(([k, label, max]) => (
        <div key={k}>
          <div className="flex justify-between text-[11px] text-muted-foreground">
            <span>{label}</span>
            <span className="tabular-nums">{max === 10 ? b[k] : `${b[k]}%`}</span>
          </div>
          <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary/70" style={{ width: `${(100 * (b[k] ?? 0)) / max}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function RenderStatus({ c, job, onWatch }: { c: Clip; job: Job | undefined; onWatch: (c: Clip) => void }) {
  const { cancel } = useJobActions()
  if (job)
    return (
      <div className="mt-2 flex items-center gap-3 rounded-lg border bg-muted/30 p-2 text-xs">
        <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
        <div className="min-w-0 flex-1">
          <div className="text-muted-foreground">{job.status === 'queued' ? 'Na fila para renderizar…' : job.message}</div>
          {job.status === 'running' && <Progress value={job.progress} className="mt-1" />}
        </div>
        <Button size="sm" variant="ghost" className="h-7" onClick={() => cancel.mutate(job.id)}>
          <Ban /> Cancelar
        </Button>
      </div>
    )
  if (c.status === 'error' && c.error)
    return (
      <div className="mt-2 flex items-center gap-2 text-xs text-destructive">
        <AlertTriangle className="size-3.5" /> Falha no render: {c.error}
      </div>
    )
  if (!c.output_path) return null
  const outdated = c.status !== 'rendered'
  return (
    <div className="mt-2 flex items-center gap-3 rounded-lg border bg-muted/30 p-2">
      <button onClick={() => onWatch(c)} className="relative shrink-0 overflow-hidden rounded" aria-label="Assistir corte">
        <img src={clipPreviewUrl(c)} alt="" width={36} height={64} loading="lazy" className="h-16 w-9 bg-black object-cover" />
        <Play className="absolute inset-0 m-auto size-4 text-white drop-shadow" />
      </button>
      <div className="min-w-0 flex-1 text-xs">
        <div className={cn('truncate', outdated ? 'text-warning' : 'text-success')}>
          {outdated ? 'MP4 desatualizado — renderize de novo para aplicar as edições' : 'MP4 pronto'}
        </div>
        <div className="truncate text-muted-foreground" title={c.output_path}>
          {c.output_path.split('/').pop()}
        </div>
      </div>
      <Button size="sm" variant="ghost" className="h-7" onClick={() => onWatch(c)}>
        <Play /> Assistir
      </Button>
      <Button size="sm" variant="ghost" className="h-7" asChild>
        <a href={clipFileUrl(c.id, true)} download>
          <Download /> Baixar
        </a>
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="size-7"
        aria-label="Abrir pasta"
        onClick={() => openFolder(c.output_path).catch((e: Error) => toast.error(e.message))}
      >
        <FolderOpen />
      </Button>
    </div>
  )
}

function WatchDialog({ c, onClose }: { c: Clip; onClose: () => void }) {
  return (
    <Dialog open onClose={onClose} title={c.title || 'Corte'} className="max-w-sm">
      <video src={clipFileUrl(c.id)} controls autoPlay playsInline className="aspect-[9/16] w-full rounded-lg bg-black" />
      <div className="mt-4 flex justify-end">
        <Button asChild>
          <a href={clipFileUrl(c.id, true)} download>
            <Download /> Baixar MP4
          </a>
        </Button>
      </div>
    </Dialog>
  )
}

function ClipRow({
  c,
  playing,
  selected,
  onPlay,
  job,
  postJob,
  postError,
  reviewJob,
  reviewError,
  onWatch,
}: {
  c: Clip
  playing: boolean
  selected: boolean
  onPlay: (c: Clip) => void
  job: Job | undefined
  postJob: Job | undefined
  postError: string
  reviewJob: Job | undefined
  reviewError: string
  onWatch: (c: Clip) => void
}) {
  const [open, setOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [postOpen, setPostOpen] = useState(false)
  const { update, duplicate, remove, render } = useClipActions(c.project_id)
  const discarded = c.status === 'discarded'
  const onError = (e: Error) => toast.error(e.message)

  return (
    <li className={cn('group px-4 py-3 transition-colors', selected && 'bg-primary/5', discarded && 'opacity-55')}>
      <div className="flex gap-3">
        <ScoreBadge c={c} />
        <div className="min-w-0 flex-1">
          <button className="block w-full text-left" onClick={() => onPlay(c)}>
            <div className="flex items-center gap-2">
              <span className={cn('truncate font-medium', discarded && 'line-through')}>{c.title || 'Sem título'}</span>
              {c.status === 'edited' && c.origin === 'ai' && <Badge variant="secondary">editado</Badge>}
              <PostPackBadge c={c} />
              <ReviewBadge c={c} />
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
              {formatTime(c.start_s)} → {formatTime(c.end_s)} · {formatDuration(c.end_s - c.start_s)}
            </div>
            {c.hook_text && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">“{c.hook_text}”</p>}
          </button>

          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            <Button size="sm" variant={playing ? 'secondary' : 'ghost'} onClick={() => onPlay(c)}>
              {playing ? <Pause /> : <Play />} {playing ? 'Pausar' : 'Tocar'}
            </Button>
            <Button size="sm" variant="ghost" asChild={!discarded} disabled={discarded}>
              {discarded ? (
                <span>
                  <Pencil /> Editar
                </span>
              ) : (
                <Link to={`/cortes/${c.id}`}>
                  <Pencil /> Editar
                </Link>
              )}
            </Button>
            <NativeSelect
              aria-label="Enquadramento"
              title="Enquadramento do corte"
              value={c.reframe_mode}
              disabled={discarded}
              onChange={(e) => update.mutate({ id: c.id, reframe_mode: e.target.value as Clip['reframe_mode'] }, { onError })}
              className="h-8 w-auto py-0 pr-7 text-xs"
            >
              {(Object.keys(REFRAME_LABELS) as Clip['reframe_mode'][])
                .filter((m) => m !== 'manual')
                .map((m) => (
                  <option key={m} value={m}>
                    {REFRAME_LABELS[m]}
                  </option>
                ))}
              {c.reframe_mode === 'manual' && <option value="manual">Manual</option>}
            </NativeSelect>
            <Button
              size="sm"
              variant="ghost"
              disabled={discarded || !!job || render.isPending}
              onClick={() => render.mutate(c.id, { onError })}
            >
              <Film /> {c.output_path ? 'Renderizar de novo' : 'Renderizar'}
            </Button>
            {discarded ? (
              <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: c.id, status: c.origin === 'ai' ? 'suggested' : 'edited' }, { onError })}>
                <ArchiveRestore /> Restaurar
              </Button>
            ) : (
              <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: c.id, status: 'discarded' }, { onError })}>
                <X /> Descartar
              </Button>
            )}
            <Button
              size="sm"
              variant={postOpen ? 'secondary' : 'ghost'}
              disabled={discarded}
              onClick={() => setPostOpen((o) => !o)}
              title="Legendas, hashtags e capa para postar"
            >
              {postJob ? <Loader2 className="animate-spin" /> : <Send />} Postar
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={discarded || c.status !== 'rendered' || !!reviewJob}
              onClick={() => setReviewOpen(true)}
              title={c.status === 'rendered' ? 'O Claude confere o MP4 final (pago — mostra o custo antes)' : 'Renderize o corte primeiro'}
            >
              {reviewJob ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Revisar
            </Button>
            <Button size="sm" variant="ghost" onClick={() => duplicate.mutate(c.id, { onError, onSuccess: () => toast.success('Corte duplicado') })}>
              <Copy /> Duplicar
            </Button>
            {c.origin === 'manual' && (
              <Button
                size="icon"
                variant="ghost"
                className="size-8 text-muted-foreground"
                aria-label="Apagar corte"
                onClick={() => window.confirm('Apagar este corte?') && remove.mutate(c.id, { onError })}
              >
                <Trash2 />
              </Button>
            )}
            {(c.reason || c.origin === 'ai') && (
              <button
                onClick={() => setOpen((o) => !o)}
                className="ml-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                Por quê? <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
              </button>
            )}
          </div>

          {!discarded && <RenderStatus c={c} job={job} onWatch={onWatch} />}
          {!discarded && <ReviewDetails c={c} job={reviewJob} error={reviewError} />}
          {!discarded && postOpen && <PostPackPanel c={c} job={postJob} lastError={postError} />}
          {reviewOpen && <ReviewDialog projectId={c.project_id} clip={c} onClose={() => setReviewOpen(false)} />}

          {open && (
            <div className="mt-2 space-y-3 rounded-lg bg-muted/40 p-3 text-sm">
              {c.reason && <p>{c.reason}</p>}
              <Breakdown c={c} />
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

function ManualClipDialog({
  projectId,
  duration,
  getTime,
  onClose,
  onCreated,
}: {
  projectId: number
  duration: number
  getTime: () => number
  onClose: () => void
  onCreated: (c: Clip) => void
}) {
  const now = getTime()
  const [start, setStart] = useState(formatTime(now))
  const [end, setEnd] = useState(formatTime(Math.min(duration, now + 30)))
  const [title, setTitle] = useState('')
  const { create } = useClipActions(projectId)
  const s = parseTime(start)
  const e = parseTime(end)
  const error =
    s == null || e == null ? 'Use o formato m:ss (ex.: 1:23.5)' : e - s < 1 ? 'O fim precisa vir depois do início' : e > duration + 0.5 ? 'Passa do fim do vídeo' : ''

  return (
    <Dialog open onClose={onClose} title="Novo corte manual" description="Escolha início e fim. Dica: pause o player no ponto desejado e use “agora”.">
      <form
        className="space-y-4"
        onSubmit={(ev) => {
          ev.preventDefault()
          if (error || s == null || e == null) return
          create.mutate(
            { start_s: s, end_s: e, title },
            {
              onSuccess: (c) => (toast.success('Corte criado — abrindo o editor'), onClose(), onCreated(c)),
              onError: (err) => toast.error(err.message),
            },
          )
        }}
      >
        <div className="grid grid-cols-2 gap-3">
          {(
            [
              ['Início', start, setStart],
              ['Fim', end, setEnd],
            ] as const
          ).map(([label, value, set]) => (
            <label key={label} className="space-y-1.5">
              <span className="text-sm font-medium">{label}</span>
              <div className="flex gap-1">
                <Input value={value} onChange={(ev) => set(ev.target.value)} className="font-mono" />
                <Button type="button" variant="outline" size="sm" className="h-9" onClick={() => set(formatTime(getTime()))}>
                  agora
                </Button>
              </div>
            </label>
          ))}
        </div>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Título (opcional)</span>
          <Input value={title} onChange={(ev) => setTitle(ev.target.value)} maxLength={200} placeholder="Gerado a partir da primeira frase…" />
        </label>
        {error ? (
          <p className="text-xs text-destructive">{error}</p>
        ) : (
          <p className="text-xs text-muted-foreground">Duração: {formatDuration((e ?? 0) - (s ?? 0))}</p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!!error || create.isPending}>
            <Plus /> Criar corte
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function RenderAllDialog({ projectId, onClose }: { projectId: number; onClose: () => void }) {
  const { data: project } = useProject(projectId)
  const current = project ? parseOptions(project).template ?? 'geral' : 'geral'
  const [choice, setChoice] = useState<string>('keep')
  const apply = useApplyTemplate(projectId)
  const { renderAll } = useClipActions(projectId)
  const busy = apply.isPending || renderAll.isPending
  const go = () => {
    const onError = (e: Error) => toast.error(e.message)
    if (choice === 'keep')
      renderAll.mutate(undefined, { onSuccess: (js) => (toast.success(`${js.length} corte(s) na fila de render`), onClose()), onError })
    else
      apply.mutate(
        { template: choice, render: true },
        { onSuccess: (r) => (toast.success(`Template aplicado a ${r.clips} corte(s); ${r.renders} na fila de render`), onClose()), onError },
      )
  }
  return (
    <Dialog open onClose={onClose} title="Renderizar todos" description="Escolha o template antes de renderizar." className="max-w-xl">
      <div className="space-y-4">
        <label
          className={cn('flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-sm', choice === 'keep' && 'border-primary bg-primary/5')}
        >
          <input type="radio" className="accent-primary" checked={choice === 'keep'} onChange={() => setChoice('keep')} />
          Manter o enquadramento de cada corte
          <span className="ml-auto text-xs text-muted-foreground">só renderiza o que mudou</span>
        </label>
        <div className="text-xs font-medium text-muted-foreground">…ou aplicar um template a todos os cortes ativos:</div>
        <TemplatePicker value={choice} onChange={(t) => setChoice(t.key)} />
        {choice !== 'keep' && (
          <p className="text-xs text-muted-foreground">
            Troca o enquadramento e a posição da legenda de todos os cortes ativos (correções de palavras e títulos ficam) e vira
            o padrão do projeto{current !== choice ? '' : ' (já é o atual)'}. Todos são renderizados de novo.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={go} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Film />} Renderizar
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

type StatusFilter = 'active' | 'discarded' | 'all'

export function ClipsPanel({
  projectId,
  duration,
  enabled,
  analyzing,
  playingId,
  selectedId,
  onPlay,
  getTime,
}: {
  projectId: number
  duration: number
  enabled: boolean
  analyzing: boolean
  playingId: number | null
  selectedId: number | null
  onPlay: (c: Clip) => void
  getTime: () => number
}) {
  const { data: clips, isLoading } = useClips(projectId, enabled)
  const [minScore, setMinScore] = useState(0)
  const [status, setStatus] = useState<StatusFilter>('active')
  const [manualOpen, setManualOpen] = useState(false)
  const [watching, setWatching] = useState<Clip | null>(null)
  const [renderAllOpen, setRenderAllOpen] = useState(false)
  const [reviewAllOpen, setReviewAllOpen] = useState(false)
  const { data: project } = useProject(projectId)
  const aiCost = project ? parseAiCost(project) : {}
  const navigate = useNavigate()
  const { data: jobs } = useJobs()
  const { postPackAll } = useClipActions(projectId)
  const { renderJobs, postJobs, postErrors, reviewJobs, reviewErrors } = useMemo(() => {
    const ids = new Set(clips?.map((c) => c.id))
    const renderJobs = new Map<number, Job>()
    const postJobs = new Map<number, Job>()
    const postErrors = new Map<number, string>()
    const reviewJobs = new Map<number, Job>()
    const reviewErrors = new Map<number, string>()
    // jobs vêm do mais novo para o mais antigo: o primeiro post_pack de cada corte é o último que rodou
    const seen = new Set<number>()
    const seenReview = new Set<number>()
    for (const j of jobs ?? []) {
      if (!ids.has(j.ref_id)) continue
      const active = j.status === 'queued' || j.status === 'running'
      if (j.type === 'render' && active) renderJobs.set(j.ref_id, j)
      if (j.type === 'review') {
        if (active) reviewJobs.set(j.ref_id, j)
        if (!seenReview.has(j.ref_id)) {
          seenReview.add(j.ref_id)
          if (j.status === 'error') reviewErrors.set(j.ref_id, j.error || 'Falha na revisão')
        }
        continue
      }
      if (j.type !== 'post_pack') continue
      if (active) postJobs.set(j.ref_id, j)
      if (!seen.has(j.ref_id)) {
        seen.add(j.ref_id)
        if (j.status === 'error') postErrors.set(j.ref_id, j.error || 'Falha ao gerar o pacote')
      }
    }
    return { renderJobs, postJobs, postErrors, reviewJobs, reviewErrors }
  }, [jobs, clips])
  const renderedCount = clips?.filter((c) => c.status !== 'discarded' && c.output_path).length ?? 0

  const visible = useMemo(() => {
    const list = (clips ?? []).filter((c) => {
      if (status === 'active' && c.status === 'discarded') return false
      if (status === 'discarded' && c.status !== 'discarded') return false
      return c.origin === 'manual' || c.score >= minScore
    })
    return list.sort((a, b) => b.score - a.score || a.start_s - b.start_s)
  }, [clips, minScore, status])

  const discardedCount = clips?.filter((c) => c.status === 'discarded').length ?? 0
  const activeCount = (clips?.length ?? 0) - discardedCount

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Scissors className="size-4" /> Cortes sugeridos
          {activeCount > 0 && <Badge variant="secondary">{activeCount}</Badge>}
        </CardTitle>
        <CardDescription>
          Ordenados pela nota de potencial viral. Clique para tocar o trecho.
          {!!aiCost.total_usd && (
            <span title="Custo real somado das análises e revisões com Claude neste projeto"> · IA paga neste projeto: {formatUsd(aiCost.total_usd)}</span>
          )}
        </CardDescription>
        <div className="col-start-2 row-span-2 row-start-1 flex gap-2 self-start justify-self-end">
          <Button size="sm" variant="outline" onClick={() => setManualOpen(true)} disabled={!enabled}>
            <Plus /> Novo corte manual
          </Button>
          <Button size="sm" disabled={!activeCount} onClick={() => setRenderAllOpen(true)}>
            <Film /> Renderizar todos
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-0">
        {!!clips?.length && (
          <div className="flex flex-wrap items-center gap-3 px-6 text-sm">
            <label className="flex items-center gap-2 text-muted-foreground">
              Nota mínima
              <NativeSelect value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="h-8 w-24">
                {[0, 50, 60, 70, 80].map((v) => (
                  <option key={v} value={v}>
                    {v === 0 ? 'todas' : `≥ ${v}`}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <div className="flex gap-1">
              {(
                [
                  ['active', 'Ativos'],
                  ['discarded', `Descartados (${discardedCount})`],
                  ['all', 'Todos'],
                ] as const
              ).map(([k, l]) => (
                <Button key={k} size="sm" variant={status === k ? 'secondary' : 'ghost'} className="h-8" onClick={() => setStatus(k)}>
                  {l}
                </Button>
              ))}
            </div>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button
                size="sm"
                className="h-8"
                variant="outline"
                disabled={!activeCount || postPackAll.isPending}
                title="A IA escreve legenda e hashtags por plataforma e escolhe a capa de cada corte ativo (só o que ainda falta)"
                onClick={() =>
                  postPackAll.mutate(undefined, {
                    onSuccess: (js) => toast.success(`${js.length} corte(s) na fila do pacote para postar`),
                    onError: (e) => toast.error(e.message),
                  })
                }
              >
                {postPackAll.isPending ? <Loader2 className="animate-spin" /> : <Send />} Pacote para postar
              </Button>
              <Button
                size="sm"
                className="h-8"
                variant="outline"
                disabled={!renderedCount}
                title="O Claude confere os MP4s finais (pago — mostra o custo antes de confirmar)"
                onClick={() => setReviewAllOpen(true)}
              >
                <ShieldCheck /> Revisar com Claude
              </Button>
              <Button size="sm" variant="outline" className="h-8" asChild={renderedCount > 0} disabled={!renderedCount}>
                {renderedCount > 0 ? (
                  <a href={exportZipUrl(projectId)} download title="MP4s + capas + textos.csv/.txt dos cortes renderizados">
                    <Package /> Exportar tudo (.zip)
                  </a>
                ) : (
                  <span title="Renderize os cortes primeiro">
                    <Package /> Exportar tudo (.zip)
                  </span>
                )}
              </Button>
            </div>
          </div>
        )}

        {!enabled && <p className="mx-6 rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">Os cortes aparecem aqui quando a análise terminar.</p>}
        {enabled && isLoading && <p className="px-6 text-sm text-muted-foreground">Carregando…</p>}
        {enabled && clips?.length === 0 && (
          <p className="mx-6 rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            {analyzing ? 'A IA está escolhendo os trechos…' : 'Nenhum corte. Reanalise com outras opções ou crie um corte manual.'}
          </p>
        )}
        {enabled && !!clips?.length && visible.length === 0 && (
          <p className="px-6 text-sm text-muted-foreground">Nenhum corte com esses filtros.</p>
        )}
        {visible.length > 0 && (
          <ul className="divide-y border-t">
            {visible.map((c) => (
              <ClipRow
                key={c.id}
                c={c}
                playing={playingId === c.id}
                selected={selectedId === c.id}
                onPlay={onPlay}
                job={renderJobs.get(c.id)}
                postJob={postJobs.get(c.id)}
                postError={postErrors.get(c.id) ?? ''}
                reviewJob={reviewJobs.get(c.id)}
                reviewError={reviewErrors.get(c.id) ?? ''}
                onWatch={setWatching}
              />
            ))}
          </ul>
        )}
      </CardContent>
      {watching && <WatchDialog c={watching} onClose={() => setWatching(null)} />}
      {reviewAllOpen && <ReviewDialog projectId={projectId} onClose={() => setReviewAllOpen(false)} />}
      {renderAllOpen && <RenderAllDialog projectId={projectId} onClose={() => setRenderAllOpen(false)} />}
      {manualOpen && (
        <ManualClipDialog
          projectId={projectId}
          duration={duration}
          getTime={getTime}
          onClose={() => setManualOpen(false)}
          onCreated={(c) => navigate(`/cortes/${c.id}`)}
        />
      )}
    </Card>
  )
}
