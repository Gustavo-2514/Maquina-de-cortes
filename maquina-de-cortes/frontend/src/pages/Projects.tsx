import { Download as DownloadIcon, Film, FolderInput, Loader2, Plus, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, PageHeader } from '@/components/Layout'
import { ProjectThumb } from '@/components/ProjectThumb'
import { ProjectStatusBadge } from '@/components/ProjectProgress'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input, Progress } from '@/components/ui/input'
import { useDownloads } from '@/api/downloads'
import { uploadProject, useProjectActions, useProjects } from '@/api/projects'
import type { Project } from '@/api/types'
import { formatDuration, formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

type Tab = 'download' | 'upload' | 'local'

function NewProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('download')
  const [localPath, setLocalPath] = useState('')
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const { data: downloads } = useDownloads()
  const { fromDownload, create, put } = useProjectActions()
  const navigate = useNavigate()

  const eligible = downloads?.filter((d) => d.status === 'done' && d.format_choice !== 'audio_mp3' && !d.project_id) ?? []
  const go = (p: Project) => {
    onClose()
    navigate(`/projetos/${p.id}?configurar=1`)
  }
  const onError = (e: Error) => toast.error(e.message)

  async function upload(file: File) {
    setUploadPct(0)
    try {
      const p = await uploadProject(file, file.name.replace(/\.[^.]+$/, ''), setUploadPct)
      put(p)
      go(p)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falha no upload')
    } finally {
      setUploadPct(null)
    }
  }

  const tabs: { key: Tab; label: string; icon: typeof Film }[] = [
    { key: 'download', label: 'De um download', icon: DownloadIcon },
    { key: 'upload', label: 'Enviar arquivo', icon: Upload },
    { key: 'local', label: 'Caminho local', icon: FolderInput },
  ]

  return (
    <Dialog open={open} onClose={uploadPct === null ? onClose : () => {}} title="Novo projeto" className="max-w-xl">
      <div className="mb-4 grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              'flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground',
              tab === key && 'bg-background text-foreground shadow-sm',
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'download' &&
        (eligible.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nenhum download de vídeo concluído sem projeto. <Link to="/downloads" className="text-primary underline" onClick={onClose}>Baixar um vídeo</Link>
          </p>
        ) : (
          <ul className="max-h-80 divide-y overflow-y-auto rounded-lg border">
            {eligible.map((d) => (
              <li key={d.id}>
                <button
                  className="flex w-full items-center gap-3 p-2 text-left hover:bg-accent/50 disabled:opacity-50"
                  disabled={fromDownload.isPending}
                  onClick={() => fromDownload.mutate(d.id, { onSuccess: go, onError })}
                >
                  {d.thumbnail_url ? (
                    <img src={d.thumbnail_url} alt="" referrerPolicy="no-referrer" className="h-10 w-16 rounded object-cover" />
                  ) : (
                    <div className="h-10 w-16 rounded bg-muted" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-sm">{d.title || d.url}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">{formatDuration(d.duration_s)}</span>
                </button>
              </li>
            ))}
          </ul>
        ))}

      {tab === 'upload' && (
        <div
          onDragOver={(e) => (e.preventDefault(), setDragging(true))}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const f = e.dataTransfer.files[0]
            if (f) upload(f)
          }}
          onClick={() => uploadPct === null && fileRef.current?.click()}
          className={cn(
            'grid cursor-pointer place-items-center gap-2 rounded-lg border-2 border-dashed p-10 text-center text-sm text-muted-foreground transition-colors',
            dragging && 'border-primary bg-primary/5',
          )}
        >
          {uploadPct === null ? (
            <>
              <Upload className="size-8" />
              Arraste um vídeo aqui ou clique para escolher
              <span className="text-xs">MP4, MKV, MOV, WEBM…</span>
            </>
          ) : (
            <div className="w-full space-y-2">
              <div>Enviando… {uploadPct.toFixed(0)}%</div>
              <Progress value={uploadPct} />
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="video/*,.mkv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload(f)
              e.target.value = ''
            }}
          />
        </div>
      )}

      {tab === 'local' && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate({ local_path: localPath }, { onSuccess: go, onError })
          }}
        >
          <Input value={localPath} onChange={(e) => setLocalPath(e.target.value)} placeholder="/home/voce/Vídeos/podcast.mp4" className="font-mono text-xs" />
          <p className="text-xs text-muted-foreground">O arquivo é usado no lugar, sem copiar — bom para vídeos enormes. Não mova nem apague enquanto usar o projeto.</p>
          <div className="flex justify-end">
            <Button type="submit" disabled={!localPath.trim() || create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" />} Criar projeto
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
}

export default function ProjectsPage() {
  const { data, isLoading, error } = useProjects()
  const [newOpen, setNewOpen] = useState(false)

  return (
    <>
      <PageHeader
        title="Projetos"
        description="Vídeos-fonte que viram cortes."
        actions={
          <Button onClick={() => setNewOpen(true)}>
            <Plus /> Novo projeto
          </Button>
        }
      />
      <div className="px-8 pb-8">
        {isLoading && <p className="text-sm text-muted-foreground">Carregando…</p>}
        {error && <p className="text-sm text-destructive">Erro ao carregar: {error.message}</p>}
        {data?.length === 0 && (
          <EmptyState
            title="Nenhum projeto ainda"
            action={
              <Button onClick={() => setNewOpen(true)}>
                <Plus /> Novo projeto
              </Button>
            }
          >
            Um projeto é um vídeo longo que vira cortes. Comece por um link na tela Início, por um download ou por um arquivo do seu computador.
          </EmptyState>
        )}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-5">
          {data?.map((p) => (
            <Link key={p.id} to={`/projetos/${p.id}`} className="group">
              <Card className="gap-0 overflow-hidden py-0 transition-colors group-hover:border-primary/50">
                <div className="relative">
                  <ProjectThumb p={p} />
                  {p.duration_s != null && (
                    <span className="absolute right-2 bottom-2 rounded bg-black/70 px-1.5 text-xs text-white tabular-nums">
                      {formatDuration(p.duration_s)}
                    </span>
                  )}
                </div>
                <div className="space-y-2 p-4">
                  <div className="truncate font-medium" title={p.name}>
                    {p.name}
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <ProjectStatusBadge p={p} />
                    <span className="text-xs text-muted-foreground">{formatRelative(p.created_at)}</span>
                  </div>
                  {p.status === 'processing' && <Progress value={p.progress} />}
                  {p.status === 'error' && <p className="truncate text-xs text-destructive">{p.error}</p>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      </div>
      <NewProjectDialog open={newOpen} onClose={() => setNewOpen(false)} />
    </>
  )
}
