import { Ban, Cpu, Loader2, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader, LoadError } from '@/components/Layout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress } from '@/components/ui/input'
import { useJobActions, useJobs } from '@/api/jobs'
import type { Job, JobStatus } from '@/api/types'
import { elapsed, formatRelative, JOB_TYPE_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

const TYPE_LABELS = JOB_TYPE_LABELS

const STATUS: Record<JobStatus, { label: string; variant: 'secondary' | 'default' | 'success' | 'destructive' | 'outline' }> = {
  queued: { label: 'Na fila', variant: 'secondary' },
  running: { label: 'Rodando', variant: 'default' },
  done: { label: 'Concluído', variant: 'success' },
  error: { label: 'Erro', variant: 'destructive' },
  canceled: { label: 'Cancelado', variant: 'outline' },
}

const FILTERS: { key: string; label: string; match: (j: Job) => boolean }[] = [
  { key: 'all', label: 'Todos', match: () => true },
  { key: 'active', label: 'Ativos', match: (j) => j.status === 'queued' || j.status === 'running' },
  { key: 'done', label: 'Concluídos', match: (j) => j.status === 'done' },
  { key: 'error', label: 'Com erro', match: (j) => j.status === 'error' },
  { key: 'canceled', label: 'Cancelados', match: (j) => j.status === 'canceled' },
]

export default function QueuePage() {
  const { data: jobs, isLoading, error } = useJobs()
  const { cancel, retry } = useJobActions()
  const [filter, setFilter] = useState('all')

  const targetName = (j: Job) => j.target ?? `#${j.ref_id}`

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, jobs?.filter(f.match).length ?? 0])), [jobs])
  const visible = jobs?.filter(FILTERS.find((f) => f.key === filter)!.match) ?? []
  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : 'Falhou')

  return (
    <>
      <PageHeader title="Fila" description="Jobs de download, transcrição, análise e render. Jobs de GPU rodam um por vez." />
      <div className="space-y-4 px-8 pb-8">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <Button key={f.key} size="sm" variant={filter === f.key ? 'secondary' : 'ghost'} onClick={() => setFilter(f.key)}>
              {f.label}
              <span className="text-xs text-muted-foreground tabular-nums">{counts[f.key]}</span>
            </Button>
          ))}
        </div>

        <Card className="overflow-hidden py-0">
          {isLoading && <p className="p-6 text-sm text-muted-foreground">Carregando…</p>}
          {error && <LoadError what="a fila" error={error} className="p-6" />}
          {jobs && visible.length === 0 && (
            <p className="p-10 text-center text-sm text-muted-foreground">
              {filter === 'all' ? 'Nada na fila. Downloads, transcrições e renders aparecem aqui enquanto rodam.' : 'Nenhum trabalho com esse filtro.'}
            </p>
          )}
          {visible.length > 0 && (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Tipo</th>
                  <th className="px-4 py-2 font-medium">Alvo</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="w-[30%] px-4 py-2 font-medium">Progresso</th>
                  <th className="px-4 py-2 font-medium">Duração</th>
                  <th className="px-4 py-2 font-medium">Criado</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {visible.map((j) => {
                  const st = STATUS[j.status]
                  return (
                    <tr key={j.id} className="align-top">
                      <td className="px-4 py-3 text-muted-foreground tabular-nums">{j.id}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1.5">
                          {TYPE_LABELS[j.type] ?? j.type}
                          {j.uses_gpu && <Cpu className="size-3.5 text-muted-foreground" aria-label="usa GPU" />}
                        </span>
                      </td>
                      <td className="max-w-64 truncate px-4 py-3" title={targetName(j)}>
                        {j.target_link ? (
                          <Link to={j.target_link} className="hover:text-primary hover:underline">
                            {targetName(j)}
                          </Link>
                        ) : (
                          targetName(j)
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={st.variant}>
                          {j.status === 'running' && <Loader2 className="animate-spin" />}
                          {st.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        {(j.status === 'running' || j.status === 'queued') && (
                          <Progress value={j.progress} className="mb-1.5" />
                        )}
                        <div className={cn('text-xs', j.status === 'error' ? 'text-destructive' : 'text-muted-foreground')}>
                          {j.status === 'error' ? j.error : j.message}
                        </div>
                        {j.status === 'error' && j.error_detail && (
                          <details className="text-xs text-muted-foreground">
                            <summary className="cursor-pointer">Detalhe técnico</summary>
                            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all">{j.error_detail}</pre>
                          </details>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground tabular-nums">{elapsed(j.started_at, j.finished_at)}</td>
                      <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">{formatRelative(j.created_at)}</td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        {(j.status === 'queued' || j.status === 'running') && (
                          <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.id, { onError })}>
                            <Ban /> Cancelar
                          </Button>
                        )}
                        {(j.status === 'error' || j.status === 'canceled') && (
                          <Button size="sm" variant="ghost" onClick={() => retry.mutate(j.id, { onError })}>
                            <RotateCcw /> Repetir
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  )
}
