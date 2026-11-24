import { Download, Film, Home, ListTodo, Settings } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useServerEvents } from '@/api/events'
import { useJobs } from '@/api/jobs'
import { Progress } from '@/components/ui/input'
import { JOB_TYPE_LABELS } from '@/lib/format'
import { cn } from '@/lib/utils'

// ordem = fluxo de trabalho: começar → revisar cortes → (fontes, fila, ajustes)
const nav = [
  { to: '/inicio', label: 'Início', icon: Home },
  { to: '/projetos', label: 'Projetos', icon: Film },
  { to: '/downloads', label: 'Downloads', icon: Download },
  { to: '/fila', label: 'Fila', icon: ListTodo },
  { to: '/configuracoes', label: 'Configurações', icon: Settings },
]

export function BrandMark({ className }: { className?: string }) {
  return <img src="/brand/logo.svg" alt="" className={cn('size-7', className)} />
}

/** Mostra o trabalho que está rodando agora — o usuário não precisa abrir a Fila para saber se algo anda. */
function NowRunning() {
  const { data: jobs } = useJobs()
  const running = jobs?.find((j) => j.status === 'running')
  const queued = jobs?.filter((j) => j.status === 'queued').length ?? 0
  if (!running && queued === 0) return null
  return (
    <Link
      to="/fila"
      className="mx-3 mb-3 block rounded-lg border bg-background/60 p-3 text-xs transition-colors hover:border-primary/40"
    >
      {running ? (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-medium text-foreground">{JOB_TYPE_LABELS[running.type] ?? running.type}</span>
            <span className="text-muted-foreground tabular-nums">{running.progress.toFixed(0)}%</span>
          </div>
          {running.target && <div className="mt-0.5 truncate text-muted-foreground">{running.target}</div>}
          <Progress value={running.progress} className="mt-2 h-1" />
        </>
      ) : null}
      {queued > 0 && (
        <div className={cn('text-muted-foreground', running && 'mt-2')}>
          {queued === 1 ? '1 trabalho aguardando' : `${queued} trabalhos aguardando`}
        </div>
      )}
    </Link>
  )
}

export function Layout() {
  const connected = useServerEvents()
  const { data: jobs } = useJobs()
  const activeJobs = jobs?.filter((j) => j.status === 'queued' || j.status === 'running').length ?? 0
  // no editor a tela inteira é do vídeo: a barra lateral vira só ícones
  const compact = useLocation().pathname.startsWith('/cortes/')

  return (
    <div className="flex h-dvh">
      <aside className={cn('flex shrink-0 flex-col border-r bg-card/50', compact ? 'w-16' : 'w-60')}>
        <Link to="/inicio" className={cn('flex items-center gap-2.5 pt-5 pb-6', compact ? 'justify-center' : 'px-5')} aria-label="Máquina de Cortes — início">
          <BrandMark />
          {!compact && (
            <span className="font-display text-[15px] leading-tight">
              Máquina
              <br />
              de Cortes
            </span>
          )}
        </Link>
        <nav className="flex flex-col gap-0.5 px-3" aria-label="Principal">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={compact ? label : undefined}
              aria-label={compact ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'relative flex items-center gap-3 rounded-md px-3 py-2 text-sm', compact && 'justify-center', ' text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground',
                  isActive &&
                    'bg-accent text-foreground before:absolute before:top-2 before:bottom-2 before:-left-3 before:w-[3px] before:rounded-r before:bg-primary',
                )
              }
            >
              <Icon className="size-4 shrink-0" />
              {!compact && label}
              {to === '/fila' && activeJobs > 0 && (
                <span className="ml-auto rounded-full bg-primary px-1.5 text-xs leading-5 font-semibold text-primary-foreground tabular-nums">
                  {activeJobs}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          {!compact && <NowRunning />}
          <div
            className={cn('flex items-center gap-2 border-t py-3 text-xs text-muted-foreground', compact ? 'justify-center' : 'px-5')}
            title={connected ? 'Conectado ao servidor local, atualizando em tempo real' : 'Sem conexão com o servidor local. Tentando reconectar…'}
          >
            <span className={cn('size-2 rounded-full', connected ? 'bg-success' : 'animate-pulse bg-destructive')} />
            {!compact && (connected ? 'Tudo roda no seu computador' : 'Reconectando ao servidor…')}
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <header className="flex items-end justify-between gap-4 px-8 pt-8 pb-6">
      <div>
        <h1 className="font-display text-3xl">{title}</h1>
        {description && <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </header>
  )
}

/** Estado vazio com ilustração: explica o que falta e oferece a próxima ação. */
export function EmptyState({
  image = '/brand/empty.webp',
  title,
  children,
  action,
}: {
  image?: string
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-10 text-center">
      <img src={image} alt="" className="w-72 rounded-xl" />
      <h2 className="mt-4 font-display text-lg">{title}</h2>
      {children && <p className="mt-1.5 text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Placeholder({ phase, children }: { phase: number; children: React.ReactNode }) {
  return (
    <div className="m-8 rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
      {children}
      <div className="mt-2 text-xs opacity-70">Chega na Fase {phase}.</div>
    </div>
  )
}
