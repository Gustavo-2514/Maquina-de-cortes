import { Gamepad2, Mic, Sparkles, Users } from 'lucide-react'
import { useTemplates } from '@/api/clips'
import type { Template } from '@/api/types'
import { cn } from '@/lib/utils'

const ICONS: Record<string, typeof Mic> = { geral: Sparkles, gameplay: Gamepad2, podcast: Mic, debate: Users }

/** Capa ilustrada de cada template (geradas no Higgsfield, em public/templates/). */
const COVERS: Record<string, string> = {
  geral: '/templates/geral.webp',
  gameplay: '/templates/gameplay.webp',
  podcast: '/templates/podcast.webp',
  debate: '/templates/debate.webp',
}

export function TemplatePicker({ value, onChange }: { value: string; onChange: (t: Template) => void }) {
  const { data: templates } = useTemplates()
  if (!templates) return null
  return (
    <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Template">
      {templates.map((t) => {
        const Icon = ICONS[t.key] ?? Sparkles
        return (
          <button
            key={t.key}
            type="button"
            role="radio"
            aria-checked={value === t.key}
            onClick={() => onChange(t)}
            className={cn(
              'group flex flex-col overflow-hidden rounded-xl border bg-card text-left transition-colors hover:border-primary/50',
              value === t.key && 'border-primary ring-1 ring-primary/40',
            )}
          >
            <div className="aspect-video w-full overflow-hidden bg-muted">
              {COVERS[t.key] && (
                <img
                  src={COVERS[t.key]}
                  alt=""
                  loading="lazy"
                  className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                />
              )}
            </div>
            <span className="min-w-0 p-2.5">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <Icon className="size-3.5" /> {t.name}
              </span>
              <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">{t.description}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
