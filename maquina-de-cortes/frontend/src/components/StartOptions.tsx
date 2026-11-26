import { Gamepad2, Mic, Sparkles, Users } from 'lucide-react'
import { useTemplates } from '@/api/clips'
import { Checkbox } from '@/components/ui/input'
import { prefsFromTemplate, saveStartPrefs, type StartPrefs } from '@/lib/startPrefs'
import { cn } from '@/lib/utils'

const ICONS: Record<string, typeof Mic> = { geral: Sparkles, gameplay: Gamepad2, podcast: Mic, debate: Users }

/** Tipo de conteúdo + "renderizar ao final", escolhidos antes de começar (o pipeline roda sozinho até o MP4). */
export function StartOptions({ value, onChange, className }: { value: StartPrefs; onChange: (p: StartPrefs) => void; className?: string }) {
  const { data: templates } = useTemplates()
  const update = (p: StartPrefs) => {
    saveStartPrefs(p)
    onChange(p)
  }
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
      <div className="flex items-center gap-1" role="radiogroup" aria-label="Tipo de conteúdo">
        {templates?.map((t) => {
          const Icon = ICONS[t.key] ?? Sparkles
          const on = value.template === t.key
          return (
            <button
              key={t.key}
              type="button"
              role="radio"
              aria-checked={on}
              title={t.description}
              onClick={() => update(prefsFromTemplate(t, value.auto_render))}
              className={cn(
                'flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors',
                on ? 'border-foreground bg-foreground text-background' : 'text-muted-foreground hover:border-foreground/50 hover:text-foreground',
              )}
            >
              <Icon aria-hidden className="size-3.5" /> {t.name}
            </button>
          )
        })}
      </div>
      <label
        className="flex cursor-pointer items-center gap-2 text-xs font-medium"
        title="Depois de achar os cortes, já gera os MP4 finais. Ideal para deixar um vídeo longo rodando à noite."
      >
        <Checkbox checked={value.auto_render} onChange={(e) => update({ ...value, auto_render: e.target.checked })} />
        Já renderizar os cortes
      </label>
    </div>
  )
}
