import { useEffect, useMemo, useRef, useState } from 'react'
import { wordKey } from '@/lib/captions'
import { snapEnd } from '@/lib/crop'
import { wordAt } from '@/lib/transcript'
import { cn } from '@/lib/utils'
import { useEditor } from '@/stores/editor'
import { useEditorCtx, useVideoTime } from './context'

const CONTEXT_S = 30

/**
 * Transcrição em volta do corte. Clique = ir até a palavra; Shift+clique = início/fim do corte;
 * duplo clique = corrigir a palavra (só na legenda deste corte, os tempos não mudam).
 */
export function ClipTranscript() {
  const { videoRef, words, project } = useEditorCtx()
  const start = useEditor((s) => s.draft?.start_s ?? 0)
  const end = useEditor((s) => s.draft?.end_s ?? 0)
  const overrides = useEditor((s) => s.draft?.words ?? {})
  const setDraft = useEditor((s) => s.set)
  const t = useVideoTime(15)
  const [editing, setEditing] = useState<string | null>(null)
  const [text, setText] = useState('')
  const boxRef = useRef<HTMLDivElement>(null)

  const visible = useMemo(() => words.filter((w) => w.e >= start - CONTEXT_S && w.s <= end + CONTEXT_S), [words, start, end])
  const active = wordAt(visible.map((w) => ({ ...w, p: 1 })), t)
  const firstIn = useMemo(() => visible.findIndex((w) => w.e > start + 0.02 && w.s < end - 0.02), [visible, start, end])

  useEffect(() => {
    const box = boxRef.current
    const el = box?.querySelector('[data-active]') as HTMLElement | null
    if (!box || !el) return
    const top = el.offsetTop - box.offsetTop
    if (top < box.scrollTop + 20 || top > box.scrollTop + box.clientHeight - 40) box.scrollTo({ top: top - box.clientHeight / 3, behavior: 'smooth' })
  }, [active])

  // ao abrir, rola até o início do corte
  useEffect(() => {
    const box = boxRef.current
    const el = box?.querySelector('[data-first-in]') as HTMLElement | null
    if (box && el) box.scrollTop = el.offsetTop - box.offsetTop - 30
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const seek = (s: number) => {
    const v = videoRef.current
    if (v) v.currentTime = s
  }

  const onClick = (w: (typeof visible)[number], e: React.MouseEvent) => {
    if (e.shiftKey) {
      // Shift+clique: palavra antes do meio do corte vira o início; depois, o fim
      if (w.s < (start + end) / 2) {
        if (end - w.s >= 1) setDraft({ start_s: w.s })
      } else {
        const en = snapEnd(words, w.e, project.duration_s ?? Infinity)
        if (en - start >= 1) setDraft({ end_s: en })
      }
      return
    }
    seek(w.s)
  }

  const commit = () => {
    if (editing === null) return
    const key = editing
    setEditing(null)
    const original = words.find((w) => wordKey(w.s) === key)?.w
    const next = { ...overrides }
    if (text.trim() === original) delete next[key]
    else next[key] = text.trim() // vazio = some da legenda
    setDraft({ words: next })
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Clique = ir até a palavra · <kbd>Shift</kbd>+clique = definir início/fim · duplo clique = corrigir a legenda
      </p>
      <div ref={boxRef} className="max-h-48 overflow-y-auto rounded-lg border p-3 text-[15px] leading-7">
        {visible.map((w, i) => {
          const key = wordKey(w.s)
          const inClip = w.e > start + 0.02 && w.s < end - 0.02
          const corrected = key in overrides
          const shown = corrected ? overrides[key] : w.w
          const markFirst = i === firstIn
          if (editing === key)
            return (
              <input
                key={key}
                autoFocus
                value={text}
                onChange={(e) => setText(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commit()
                  if (e.key === 'Escape') setEditing(null)
                  e.stopPropagation()
                }}
                style={{ width: `${Math.max(3, text.length + 1)}ch` }}
                className="mx-0.5 rounded border border-primary bg-background px-0.5 outline-none"
              />
            )
          return (
            <span key={key}>
              <span
                data-active={i === active || undefined}
                data-first-in={markFirst || undefined}
                onClick={(e) => onClick(w, e)}
                onDoubleClick={() => {
                  setEditing(key)
                  setText(shown)
                }}
                title={corrected ? `Original: “${w.w}”` : undefined}
                className={cn(
                  'cursor-pointer rounded px-0.5 hover:bg-accent',
                  !inClip && 'text-muted-foreground/50',
                  corrected && 'underline decoration-primary decoration-2 underline-offset-4',
                  corrected && !shown && 'line-through',
                  i === active && 'bg-primary text-primary-foreground hover:bg-primary',
                )}
              >
                {shown || w.w}
              </span>{' '}
            </span>
          )
        })}
      </div>
    </div>
  )
}
