import { Check, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/input'
import type { Project } from '@/api/types'
import { cn } from '@/lib/utils'

const STEPS: { key: string; label: string; stages: Project['stage'][] }[] = [
  { key: 'prep', label: 'Preparar vídeo', stages: ['probe', 'proxy'] },
  { key: 'transcribe', label: 'Transcrever', stages: ['transcribe'] },
  { key: 'analyze', label: 'Encontrar cortes', stages: ['analyze'] },
]

const ORDER: Project['stage'][] = ['probe', 'proxy', 'transcribe', 'analyze', 'done']

export function ProjectStatusBadge({ p }: { p: Project }) {
  if (p.status === 'ready') return <Badge variant="success">Pronto</Badge>
  if (p.status === 'error') return <Badge variant="destructive">Erro</Badge>
  if (p.status === 'new') return <Badge variant="secondary">Novo</Badge>
  const step = STEPS.find((s) => s.stages.includes(p.stage))
  return (
    <Badge>
      <Loader2 className="animate-spin" />
      {step?.label ?? 'Processando'}
    </Badge>
  )
}

/** Etapas do pipeline com progresso da etapa atual. */
export function ProjectSteps({ p }: { p: Project }) {
  const cur = ORDER.indexOf(p.stage)
  return (
    <ol className="space-y-3">
      {STEPS.map((s) => {
        const idx = Math.max(...s.stages.map((x) => ORDER.indexOf(x)))
        const first = Math.min(...s.stages.map((x) => ORDER.indexOf(x)))
        const active = p.status === 'processing' && s.stages.includes(p.stage)
        const done = cur > idx || p.status === 'ready'
        const failed = p.status === 'error' && s.stages.includes(p.stage)
        return (
          <li key={s.key} className="flex items-center gap-3 text-sm">
            <span
              className={cn(
                'grid size-6 shrink-0 place-items-center rounded-full border text-xs',
                done && 'border-foreground bg-foreground text-background',
                active && 'border-primary text-primary',
                failed && 'border-destructive text-destructive',
              )}
            >
              {done ? <Check className="size-3.5" /> : active ? <Loader2 className="size-3.5 animate-spin" /> : first + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className={cn(!done && !active && 'text-muted-foreground')}>
                {s.label}
              </div>
              {active && <Progress value={p.progress} className="mt-1.5" />}
            </div>
            {active && <span className="text-xs text-muted-foreground tabular-nums">{p.progress.toFixed(0)}%</span>}
          </li>
        )
      })}
    </ol>
  )
}
