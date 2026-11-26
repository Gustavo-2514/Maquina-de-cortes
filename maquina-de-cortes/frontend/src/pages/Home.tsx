import { Link2, Loader2, Pause, Play, Scissors, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ApiError } from '@/api/client'
import { fetchLinkInfo, useDownloadActions, useDownloads } from '@/api/downloads'
import { uploadProject, useProjectActions, useProjects } from '@/api/projects'
import { ProjectStatusBadge } from '@/components/ProjectProgress'
import { ProjectThumb } from '@/components/ProjectThumb'
import { Button } from '@/components/ui/button'
import type { FormatChoice } from '@/api/types'
import { NativeSelect, Progress } from '@/components/ui/input'
import { FORMAT_LABELS, formatDuration, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

const STEPS = [
  {
    img: '/brand/step1.webp',
    title: 'Traga o vídeo longo',
    text: 'Um link do YouTube, Twitch, TikTok ou X, ou um arquivo do seu computador. Podcasts, lives e gameplays funcionam melhor.',
  },
  {
    img: '/brand/step2.webp',
    title: 'A IA escolhe os trechos',
    text: 'O vídeo é transcrito e cada trecho recebe uma nota de potencial viral. Você vê os melhores primeiro.',
  },
  {
    img: '/brand/step3.webp',
    title: 'Ajuste e exporte',
    text: 'Enquadramento vertical no rosto de quem fala, legendas animadas e título. Exporta em MP4 1080×1920.',
  },
]

function HeroVideo() {
  // respeita “reduzir movimento”: mostra só o quadro estático
  const reduce = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const ref = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(!reduce)
  function toggle() {
    const v = ref.current
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }
  return (
    <div className="enter relative aspect-video overflow-hidden rounded-2xl border bg-black" style={{ '--enter-delay': '180ms' } as React.CSSProperties}>
      <video
        ref={ref}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        width={1280}
        height={720}
        src="/brand/hero.mp4"
        poster="/brand/hero.webp"
        autoPlay={!reduce}
        muted
        loop
        playsInline
        aria-hidden
        className="size-full object-cover grayscale"
      />
      {/* loop decorativo com mais de 5 s: precisa de pausa (diretriz de acessibilidade) */}
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? 'Pausar animação' : 'Reproduzir animação'}
        className="absolute right-3 bottom-3 grid size-9 place-items-center rounded-full border border-white/20 bg-black/70 text-white transition-[border-color,transform] hover:border-white/60 active:scale-95"
      >
        {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
      </button>
    </div>
  )
}

// este fluxo sempre vira cortes: só formatos com vídeo
const VIDEO_FORMATS = ['best', '1080p', '720p'] as const satisfies readonly FormatChoice[]
type VideoFormat = (typeof VIDEO_FORMATS)[number]
const QUALITY_KEY = 'mdc.downloadQuality'

function loadQuality(): VideoFormat {
  const v = localStorage.getItem(QUALITY_KEY)
  return (VIDEO_FORMATS as readonly string[]).includes(v ?? '') ? (v as VideoFormat) : 'best'
}

function StartBox() {
  const [link, setLink] = useState('')
  const [quality, setQuality] = useState<VideoFormat>(loadQuality)
  const [busy, setBusy] = useState(false)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const { create } = useDownloadActions()
  const { put } = useProjectActions()
  const navigate = useNavigate()

  async function fromLink() {
    const url = link.trim()
    if (!/^https?:\/\//i.test(url)) {
      toast.error('Cole um link completo, começando com https://')
      return
    }
    setBusy(true)
    try {
      const info = await fetchLinkInfo(url)
      if (info.kind === 'playlist') {
        // playlist: o usuário escolhe quais vídeos na tela de Downloads
        navigate(`/downloads?links=${encodeURIComponent(url)}`)
        return
      }
      await create.mutateAsync([
        {
          url,
          format_choice: quality,
          send_to_project: true,
          title: info.title,
          uploader: info.uploader,
          duration_s: info.duration_s,
          thumbnail_url: info.thumbnail_url,
        },
      ])
      toast.success('Baixando o vídeo', { description: 'Depois ele é transcrito e analisado sozinho. Acompanhe abaixo.' })
      setLink('')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Não consegui ler esse link', {
        description: 'Confira se o vídeo é público. Na tela de Downloads dá para tentar baixar mesmo assim.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function fromFile(file: File) {
    setUploadPct(0)
    try {
      const p = await uploadProject(file, file.name.replace(/\.[^.]+$/, ''), setUploadPct)
      put(p)
      navigate(`/projetos/${p.id}?configurar=1`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falha ao enviar o arquivo')
    } finally {
      setUploadPct(null)
    }
  }

  return (
    <div
      onDragOver={(e) => (e.preventDefault(), setDragging(true))}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const f = e.dataTransfer.files[0]
        if (f) fromFile(f)
      }}
      className={cn('rounded-xl border bg-card p-2 transition-colors focus-within:border-foreground/40', dragging && 'border-primary')}
    >
      {uploadPct !== null ? (
        <div className="space-y-2 p-3 text-sm">
          <div className="flex justify-between">
            <span>Enviando o arquivo…</span>
            <span className="tabular-nums text-muted-foreground">{uploadPct.toFixed(0)}%</span>
          </div>
          <Progress value={uploadPct} />
        </div>
      ) : (
        <form
          noValidate
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            fromLink()
          }}
        >
          <Link2 aria-hidden className="ml-2 size-5 shrink-0 text-muted-foreground" />
          <input
            value={link}
            onChange={(e) => setLink(e.target.value)}
            placeholder={dragging ? 'Solte o vídeo aqui' : 'Cole o link do vídeo…'}
            aria-label="Link do vídeo"
            type="url"
            name="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            autoFocus
            className="h-11 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground focus-visible:outline-none"
          />
          <NativeSelect
            value={quality}
            onChange={(e) => {
              const v = e.target.value as VideoFormat
              setQuality(v)
              localStorage.setItem(QUALITY_KEY, v)
            }}
            aria-label="Qualidade do download"
            title="Qualidade do download. Menor qualidade baixa mais rápido e ocupa menos espaço."
            className="h-11 w-auto shrink-0"
          >
            {VIDEO_FORMATS.map((f) => (
              <option key={f} value={f}>
                {f === 'best' ? 'Melhor qualidade' : FORMAT_LABELS[f]}
              </option>
            ))}
          </NativeSelect>
          <Button type="submit" size="lg" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Scissors />}
            Criar cortes
          </Button>
        </form>
      )}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t px-3 pt-2 pb-1 text-xs text-muted-foreground">
        <span>Também dá para arrastar um arquivo de vídeo até aqui.</span>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="flex min-h-8 items-center gap-1.5 rounded px-1 font-medium text-foreground"
        >
          <Upload aria-hidden className="size-3.5" /> <span className="link-draw">Escolher arquivo</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="video/*,.mkv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) fromFile(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}

/** Downloads e projetos que ainda estão andando, num lugar só. */
function InProgress() {
  const { data: downloads } = useDownloads()
  const { data: projects } = useProjects()
  const dls = downloads?.filter((d) => d.status === 'queued' || d.status === 'downloading') ?? []
  const procs = projects?.filter((p) => p.status === 'processing') ?? []
  if (dls.length + procs.length === 0) return null
  return (
    <section>
      <h2 className="mb-3 font-display text-lg">Em andamento</h2>
      <ul className="divide-y rounded-xl border bg-card">
        {dls.map((d) => (
          <li key={`d${d.id}`} className="flex items-center gap-4 px-4 py-3">
            {d.thumbnail_url ? (
              <img src={d.thumbnail_url} alt="" width={64} height={40} referrerPolicy="no-referrer" className="h-10 w-16 shrink-0 rounded object-cover" />
            ) : (
              <div className="h-10 w-16 shrink-0 rounded bg-muted" />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{d.title || d.url}</div>
              <div className="mt-1.5 flex items-center gap-3">
                <Progress value={d.progress} className="flex-1" />
                <span className="w-28 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
                  {d.status === 'queued' ? 'na fila' : `baixando ${d.progress.toFixed(0)}%`}
                </span>
              </div>
            </div>
          </li>
        ))}
        {procs.map((p) => (
          <li key={`p${p.id}`}>
            <Link to={`/projetos/${p.id}`} className="flex items-center gap-4 px-4 py-3 hover:bg-accent/40">
              <div className="h-10 w-16 shrink-0 overflow-hidden rounded">
                <ProjectThumb p={p} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{p.name}</span>
                  <ProjectStatusBadge p={p} />
                </div>
                <div className="mt-1.5 flex items-center gap-3">
                  <Progress value={p.progress} className="flex-1" />
                  <span className="w-28 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{p.progress.toFixed(0)}%</span>
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Recent() {
  const { data } = useProjects()
  const recent = data?.filter((p) => p.status !== 'processing').slice(0, 4) ?? []
  if (recent.length === 0) return null
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="font-display text-lg">Continuar editando</h2>
        <Link to="/projetos" className="link-draw text-sm text-muted-foreground hover:text-foreground">
          Ver todos os projetos
        </Link>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {recent.map((p) => (
          <Link key={p.id} to={`/projetos/${p.id}`} className="group lift rounded-lg">
            <div className="relative overflow-hidden rounded-lg border transition-colors group-hover:border-foreground/50">
              <div className="zoom-in-frame">
                <ProjectThumb p={p} />
              </div>
              {p.duration_s != null && (
                <span className="absolute right-1.5 bottom-1.5 rounded bg-black/75 px-1.5 text-xs text-white tabular-nums">
                  {formatDuration(p.duration_s)}
                </span>
              )}
            </div>
            <div className="mt-2 line-clamp-2 text-sm leading-snug font-medium">{p.name}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{formatRelative(p.created_at)}</div>
          </Link>
        ))}
      </div>
    </section>
  )
}

export default function HomePage() {
  const { data: projects } = useProjects()
  const firstTime = projects?.length === 0

  return (
    <div className="mx-auto max-w-6xl space-y-12 px-5 py-8 md:px-8 md:py-10">
      <section className="grid grid-cols-[minmax(0,1fr)] items-center gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div>
          <h1 className="enter font-display text-3xl sm:text-4xl xl:text-5xl">
            Vídeo longo entra,
            <br />
            cortes virais saem.
          </h1>
          <p className="enter mt-4 max-w-md text-base text-muted-foreground" style={{ '--enter-delay': '60ms' } as React.CSSProperties}>
            Cole o link de um podcast, live ou gameplay. A Máquina baixa, transcreve e separa os melhores trechos em vídeos verticais com
            legenda, sem enviar nada para a nuvem.
          </p>
          <div className="enter mt-7" style={{ '--enter-delay': '120ms' } as React.CSSProperties}>
            <StartBox />
          </div>
        </div>
        <HeroVideo />
      </section>

      <InProgress />
      <Recent />

      <section className={cn(!firstTime && 'border-t pt-10')}>
        <h2 className="mb-5 font-display text-lg">Como funciona</h2>
        <ol className="grid gap-6 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <img src={s.img} alt="" width={880} height={663} loading="lazy" className="aspect-[4/3] h-auto w-full rounded-xl border object-cover grayscale" />
              <h3 className="mt-3 flex items-baseline gap-2 font-semibold">
                <span className="grid size-6 shrink-0 place-items-center rounded-full border border-foreground/40 text-xs font-medium tabular-nums">
                  {i + 1}
                </span>
                {s.title}
              </h3>
              <p className="mt-1 pl-8 text-sm text-muted-foreground">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
