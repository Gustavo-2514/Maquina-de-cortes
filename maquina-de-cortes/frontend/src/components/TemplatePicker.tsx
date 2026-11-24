import { Gamepad2, Mic, Sparkles, Users } from 'lucide-react'
import { useTemplates } from '@/api/clips'
import type { Template } from '@/api/types'
import { cn } from '@/lib/utils'

const ICONS: Record<string, typeof Mic> = { geral: Sparkles, gameplay: Gamepad2, podcast: Mic, debate: Users }

/** Miniatura do layout 9:16 de cada template. */
function LayoutSketch({ k }: { k: string }) {
  const box = 'rounded-[2px] bg-muted-foreground/40'
  return (
    <div className="flex h-12 w-[27px] shrink-0 flex-col gap-[2px] rounded-sm border border-muted-foreground/40 p-[2px]">
      {k === 'gameplay' && (
        <>
          <div className={cn(box, 'h-[40%] bg-primary/60')} />
          <div className={cn(box, 'flex-1')} />
        </>
      )}
      {k === 'debate' && (
        <>
          <div className={cn(box, 'h-1/2 bg-primary/60')} />
          <div className={cn(box, 'h-1/2 bg-primary/30')} />
        </>
      )}
      {(k === 'podcast' || k === 'geral') && <div className={cn(box, 'flex-1', k === 'podcast' && 'bg-primary/60')} />}
    </div>
  )
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
              'flex gap-2.5 rounded-lg border p-2.5 text-left transition-colors hover:border-primary/50',
              value === t.key && 'border-primary bg-primary/5 ring-1 ring-primary/40',
            )}
          >
            <LayoutSketch k={t.key} />
            <span className="min-w-0">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                <Icon className="size-3.5" /> {t.name}
              </span>
              <span className="block text-[11px] leading-snug text-muted-foreground">{t.description}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
