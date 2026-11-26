import {
  AlertTriangle,
  Ban,
  Check,
  Download as DownloadIcon,
  FolderOpen,
  ListVideo,
  Loader2,
  RotateCcw,
  Scissors,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, PageHeader, LoadError } from '@/components/Layout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox, NativeSelect, Progress, Textarea } from '@/components/ui/input'
import { StartOptions } from '@/components/StartOptions'
import { ApiError } from '@/api/client'
import { useProjectActions } from '@/api/projects'
import { fetchLinkInfo, openFolder, useDownloadActions, useDownloads, type NewDownload } from '@/api/downloads'
import type { Download, FormatChoice, LinkInfo } from '@/api/types'
import { FORMAT_LABELS, formatBytes, formatDuration, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { loadStartPrefs } from '@/lib/startPrefs'

// ---------------------------------------------------------------------------
// Análise de links
// ---------------------------------------------------------------------------

type Analyzed =
  | { key: string; url: string; state: 'loading' }
  | { key: string; url: string; state: 'error'; message: string; technical?: string }
  | { key: string; url: string; state: 'ok'; info: LinkInfo }

/** Item baixável (vídeo único ou entrada de playlist). */
interface Candidate {
  id: string
  url: string
  title: string
  uploader: string
  duration_s: number | null
  thumbnail_url: string
}

function parseLinks(text: string): string[] {
  const seen = new Set<string>()
  return text
    .split(/[\s]+/)
    .map((s) => s.trim())
    .filter((s) => /^https?:\/\//i.test(s))
    .filter((s) => (seen.has(s) ? false : (seen.add(s), true)))
}

function Thumb({ src, className }: { src: string; className?: string }) {
  return src ? (
    <img src={src} alt="" loading="lazy" referrerPolicy="no-referrer" className={cn('rounded-md bg-muted object-cover', className)} />
  ) : (
    <div className={cn('grid place-items-center rounded-md bg-muted text-muted-foreground', className)}>
      <ListVideo className="size-5" />
    </div>
  )
}

function AnalyzePanel() {
  // a tela Início manda playlists para cá com ?links=…
  const [params] = useSearchParams()
  const [text, setText] = useState(() => params.get('links') ?? '')
  const [results, setResults] = useState<Analyzed[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // mesma escolha do Início (playlists chegam por lá)
  const [format, setFormat] = useState<FormatChoice>(() => {
    const v = localStorage.getItem('mdc.downloadQuality')
    return v && v in FORMAT_LABELS ? (v as FormatChoice) : 'best'
  })
  const [sendToProject, setSendToProject] = useState(false)
  const [prefs, setPrefs] = useState(loadStartPrefs)
  const { create } = useDownloadActions()

  const analyzing = results.some((r) => r.state === 'loading')

  const candidates = useMemo(() => {
    const out: Candidate[] = []
    for (const r of results) {
      if (r.state === 'ok' && r.info.kind === 'video') out.push({ id: r.key, ...r.info })
      if (r.state === 'ok' && r.info.kind === 'playlist')
        r.info.entries.forEach((e, i) => out.push({ id: `${r.key}#${i}`, ...e }))
      if (r.state === 'error')
        out.push({ id: r.key, url: r.url, title: r.url, uploader: '', duration_s: null, thumbnail_url: '' })
    }
    return out
  }, [results])

  const toggle = (id: string, on?: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (on ?? !next.has(id)) next.add(id)
      else next.delete(id)
      return next
    })

  async function analyze() {
    const links = parseLinks(text)
    if (links.length === 0) {
      toast.error('Cole pelo menos um link começando com http:// ou https://')
      return
    }
    const batch = Date.now()
    const initial: Analyzed[] = links.map((url, i) => ({ key: `${batch}-${i}`, url, state: 'loading' }))
    setResults(initial)
    setSelected(new Set())
    await Promise.all(
      initial.map(async ({ key, url }) => {
        try {
          const info = await fetchLinkInfo(url)
          setResults((prev) => prev.map((r) => (r.key === key ? { key, url, state: 'ok', info } : r)))
          // seleciona tudo por padrão (vídeo ou todas as entradas da playlist)
          setSelected((prev) => {
            const next = new Set(prev)
            if (info.kind === 'video') next.add(key)
            else info.entries.forEach((_e, i) => next.add(`${key}#${i}`))
            return next
          })
        } catch (e) {
          const err = e instanceof ApiError ? e : null
          setResults((prev) =>
            prev.map((r) =>
              r.key === key
                ? { key, url, state: 'error', message: err?.message ?? String(e), technical: err?.technical }
                : r,
            ),
          )
        }
      }),
    )
  }

  async function startDownloads() {
    const chosen = candidates.filter((c) => selected.has(c.id))
    if (chosen.length === 0) return
    const items: NewDownload[] = chosen.map((c) => ({
      url: c.url,
      format_choice: format,
      send_to_project: sendToProject,
      analyze: sendToProject ? prefs : undefined,
      title: c.title === c.url ? '' : c.title,
      uploader: c.uploader,
      duration_s: c.duration_s,
      thumbnail_url: c.thumbnail_url,
    }))
    try {
      await create.mutateAsync(items)
      toast.success(chosen.length === 1 ? 'Download adicionado à fila' : `${chosen.length} downloads adicionados à fila`)
      setResults([])
      setSelected(new Set())
      setText('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falha ao criar downloads')
    }
  }

  // link vindo do Início: já analisa sozinho
  const autoRan = useRef(false)
  useEffect(() => {
    if (autoRan.current || !params.get('links')) return
    autoRan.current = true
    analyze()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const nSelected = candidates.filter((c) => selected.has(c.id)).length

  return (
    <Card className="gap-4">
      <CardContent className="space-y-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) analyze()
          }}
          placeholder="Cole o link aqui — YouTube, Twitch, TikTok, Instagram, X… (vários? um por linha)"
          className="min-h-20 resize-y text-base"
          autoFocus
        />
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">Ctrl+Enter para analisar. Playlists mostram a lista de vídeos.</p>
          <Button onClick={analyze} disabled={analyzing || !text.trim()}>
            {analyzing ? <Loader2 className="animate-spin" /> : <Search />}
            Analisar
          </Button>
        </div>

        {results.length > 0 && (
          <div className="space-y-3 border-t pt-4">
            {results.map((r) => (
              <AnalyzedItem key={r.key} item={r} selected={selected} toggle={toggle} />
            ))}

            <div className="sticky bottom-0 flex flex-wrap items-center gap-3 rounded-lg border bg-card/95 p-3 backdrop-blur">
              <label className="flex items-center gap-2 text-sm">
                Qualidade
                <NativeSelect value={format} onChange={(e) => {
                    const v = e.target.value as FormatChoice
                    setFormat(v)
                    localStorage.setItem('mdc.downloadQuality', v)
                  }} className="w-44">
                  {Object.entries(FORMAT_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label
                className="flex cursor-pointer items-center gap-2 text-sm"
                title="Quando o download terminar, o projeto é criado e a análise começa sozinha."
              >
                <Checkbox checked={sendToProject} onChange={(e) => setSendToProject(e.target.checked)} disabled={format === 'audio_mp3'} />
                Enviar para cortes após baixar
              </label>
              {sendToProject && format !== 'audio_mp3' && <StartOptions value={prefs} onChange={setPrefs} className="basis-full" />}
              <div className="ml-auto flex items-center gap-2">
                <Button variant="ghost" onClick={() => (setResults([]), setSelected(new Set()))}>
                  Limpar
                </Button>
                <Button onClick={startDownloads} disabled={nSelected === 0 || create.isPending}>
                  {create.isPending ? <Loader2 className="animate-spin" /> : <DownloadIcon />}
                  Baixar {nSelected > 0 && `(${nSelected})`}
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function AnalyzedItem({
  item,
  selected,
  toggle,
}: {
  item: Analyzed
  selected: Set<string>
  toggle: (id: string, on?: boolean) => void
}) {
  if (item.state === 'loading')
    return (
      <div className="flex items-center gap-3 rounded-lg border p-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        <span className="truncate">Analisando {item.url}</span>
      </div>
    )

  if (item.state === 'error')
    return (
      <div className="flex items-start gap-3 rounded-lg border border-destructive/40 p-3">
        <Checkbox checked={selected.has(item.key)} onChange={() => toggle(item.key)} className="mt-0.5" />
        <div className="min-w-0 flex-1 text-sm">
          <div className="flex items-center gap-2 font-medium text-destructive">
            <AlertTriangle className="size-4" /> {item.message}
          </div>
          <div className="truncate text-xs text-muted-foreground">{item.url}</div>
          {item.technical && (
            <details className="mt-1 text-xs text-muted-foreground">
              <summary className="cursor-pointer">Detalhe técnico</summary>
              <pre className="mt-1 whitespace-pre-wrap break-all">{item.technical}</pre>
            </details>
          )}
          <div className="mt-1 text-xs text-muted-foreground">Marque para tentar baixar mesmo assim.</div>
        </div>
      </div>
    )

  const { info } = item
  if (info.kind === 'video')
    return (
      <label className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 hover:bg-accent/40">
        <Checkbox checked={selected.has(item.key)} onChange={() => toggle(item.key)} />
        <Thumb src={info.thumbnail_url} className="h-16 w-28 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{info.title}</div>
          <div className="truncate text-sm text-muted-foreground">
            {info.uploader || '—'} · {formatDuration(info.duration_s)}
            {info.heights.length > 0 && ` · até ${Math.max(...info.heights)}p`}
          </div>
          {info.is_live && <Badge variant="warning" className="mt-1">Ao vivo</Badge>}
        </div>
      </label>
    )

  const ids = info.entries.map((_e, i) => `${item.key}#${i}`)
  const all = ids.length > 0 && ids.every((id) => selected.has(id))
  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-3 border-b p-3">
        <ListVideo className="size-5 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{info.title}</div>
          <div className="text-sm text-muted-foreground">
            Playlist · {info.entries.length} vídeos{info.uploader && ` · ${info.uploader}`}
          </div>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={all} onChange={() => ids.forEach((id) => toggle(id, !all))} />
          Selecionar todos
        </label>
      </div>
      <ul className="max-h-80 divide-y overflow-y-auto">
        {info.entries.map((e, i) => (
          <li key={ids[i]}>
            <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/40">
              <Checkbox checked={selected.has(ids[i])} onChange={() => toggle(ids[i])} />
              <span className="w-6 text-right text-xs text-muted-foreground tabular-nums">{i + 1}</span>
              <Thumb src={e.thumbnail_url} className="h-9 w-16 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm">{e.title}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{formatDuration(e.duration_s)}</span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Histórico
// ---------------------------------------------------------------------------

const STATUS: Record<Download['status'], { label: string; variant: 'secondary' | 'default' | 'success' | 'destructive' | 'outline' }> = {
  queued: { label: 'Na fila', variant: 'secondary' },
  downloading: { label: 'Baixando', variant: 'default' },
  done: { label: 'Concluído', variant: 'success' },
  error: { label: 'Erro', variant: 'destructive' },
  canceled: { label: 'Cancelado', variant: 'outline' },
}

function DownloadRow({ d }: { d: Download }) {
  const { cancel, retry, remove } = useDownloadActions()
  const { fromDownload } = useProjectActions()
  const navigate = useNavigate()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const active = d.status === 'queued' || d.status === 'downloading'
  const st = STATUS[d.status]

  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : 'Falhou')

  return (
    <li className="flex gap-4 px-4 py-3">
      <Thumb src={d.thumbnail_url} className="h-[72px] w-32 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium" title={d.title || d.url}>
              {d.title || d.url}
            </div>
            <div className="truncate text-xs text-muted-foreground">
              {[d.uploader, formatDuration(d.duration_s), FORMAT_LABELS[d.format_choice], d.status === 'done' && formatBytes(d.filesize), formatRelative(d.created_at)]
                .filter(Boolean)
                .join(' · ')}
            </div>
          </div>
          <Badge variant={st.variant}>
            {d.status === 'downloading' && <Loader2 className="animate-spin" />}
            {st.label}
          </Badge>
        </div>

        {active && (
          <div className="flex items-center gap-3">
            <Progress value={d.progress} className="flex-1" />
            <span className="w-40 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
              {d.status === 'queued' ? 'aguardando…' : `${d.progress.toFixed(0)}%${d.speed ? ` · ${d.speed}` : ''}${d.eta ? ` · ${d.eta}` : ''}`}
            </span>
          </div>
        )}

        {d.status === 'error' && (
          <div className="text-sm text-destructive">
            {d.error}
            {d.error_detail && (
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">Detalhe técnico</summary>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all">{d.error_detail}</pre>
              </details>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1">
          {active && (
            <Button size="sm" variant="ghost" onClick={() => cancel.mutate(d.id, { onError })}>
              <Ban /> Cancelar
            </Button>
          )}
          {(d.status === 'error' || d.status === 'canceled') && (
            <Button size="sm" variant="ghost" onClick={() => retry.mutate(d.id, { onError })}>
              <RotateCcw /> Tentar de novo
            </Button>
          )}
          {d.status === 'done' && (
            <>
              {d.project_id ? (
                <Button size="sm" variant="ghost" onClick={() => navigate(`/projetos/${d.project_id}`)}>
                  <Scissors /> Abrir projeto
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={d.format_choice === 'audio_mp3' || fromDownload.isPending}
                  title={d.format_choice === 'audio_mp3' ? 'Download só de áudio — baixe em vídeo para criar cortes' : 'Criar projeto de cortes'}
                  onClick={() =>
                    fromDownload.mutate(d.id, {
                      onSuccess: (p) => navigate(`/projetos/${p.id}?configurar=1`),
                      onError,
                    })
                  }
                >
                  {fromDownload.isPending ? <Loader2 className="animate-spin" /> : <Scissors />} Criar cortes
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => openFolder(d.file_path).catch(onError)}>
                <FolderOpen /> Abrir pasta
              </Button>
            </>
          )}
          <div className="ml-auto flex items-center gap-1">
            {confirmDelete ? (
              <>
                <span className="text-xs text-muted-foreground">Apagar:</span>
                <Button size="sm" variant="ghost" onClick={() => remove.mutate({ id: d.id, deleteFile: false }, { onError })}>
                  Só da lista
                </Button>
                {d.status === 'done' && (
                  <Button size="sm" variant="destructive" onClick={() => remove.mutate({ id: d.id, deleteFile: true }, { onError })}>
                    Lista + arquivo
                  </Button>
                )}
                <Button size="icon" variant="ghost" className="size-8" onClick={() => setConfirmDelete(false)} aria-label="Não apagar">
                  <X />
                </Button>
              </>
            ) : (
              <Button size="icon" variant="ghost" className="size-8 text-muted-foreground" onClick={() => setConfirmDelete(true)} aria-label="Apagar">
                <Trash2 />
              </Button>
            )}
          </div>
        </div>
      </div>
    </li>
  )
}

export default function DownloadsPage() {
  const { data, isLoading, error } = useDownloads()
  const activeCount = data?.filter((d) => d.status === 'queued' || d.status === 'downloading').length ?? 0
  const doneCount = data?.filter((d) => d.status === 'done').length ?? 0

  return (
    <>
      <PageHeader title="Downloads" description="Baixe vídeos do YouTube, Twitch, TikTok, Instagram, X e outros." />
      <div className="max-w-5xl space-y-6 px-8 pb-8">
        <AnalyzePanel />

        <section>
          <div className="mb-3 flex items-center gap-3">
            <h2 className="font-semibold">Histórico</h2>
            {activeCount > 0 && <Badge>{activeCount} em andamento</Badge>}
            {doneCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Check className="size-3" /> {doneCount} concluído(s)
              </span>
            )}
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => openFolder('').catch(() => {})}>
              <FolderOpen /> Pasta de downloads
            </Button>
          </div>
          <Card className="py-0">
            {isLoading && <p className="p-6 text-sm text-muted-foreground">Carregando…</p>}
            {error && <LoadError what="os downloads" error={error} className="p-6" />}
            {data?.length === 0 && (
              <EmptyState title="Nenhum download ainda">Cole um link acima. O vídeo baixado fica aqui e pode virar um projeto de cortes.</EmptyState>
            )}
            {!!data?.length && (
              <ul className="divide-y">
                {data.map((d) => (
                  <DownloadRow key={d.id} d={d} />
                ))}
              </ul>
            )}
          </Card>
        </section>
      </div>
    </>
  )
}
