/**
 * Espelho de backend/app/services/captions.py (group_lines / caption_spans / clip_words).
 * Os dois lados rodam os mesmos casos: backend/tests/fixtures/captions_cases.json.
 */

export interface CWord {
  w: string
  s: number
  e: number
}

export interface Span {
  s: number
  e: number
  line: string[]
  current: number | null
}

export const MAX_LINE_CHARS = 18
export const LINE_BREAK_PAUSE_S = 0.35
export const HOLD_GAP_S = 0.6
export const HOLD_AFTER_S = 0.25
const BREAK_PUNCT = ['.', ',', '?', '!', '…', ';', ':']

const round3 = (x: number) => Math.round(x * 1000) / 1000

/** Chave de correção de palavra: início absoluto com 3 casas (igual ao Python f"{s:.3f}"). */
export const wordKey = (s: number) => s.toFixed(3)

export function clipWords(words: CWord[], start: number, end: number, overrides: Record<string, string> = {}): CWord[] {
  const dur = end - start
  const out: CWord[] = []
  for (const w of words) {
    if (w.e <= start + 0.02 || w.s >= end - 0.02) continue
    const text = (overrides[wordKey(w.s)] ?? w.w).trim()
    if (!text) continue
    out.push({ w: text, s: round3(Math.max(0, w.s - start)), e: round3(Math.min(dur, w.e - start)) })
  }
  return out
}

export function groupLines(words: CWord[], wordsPerLine: number, maxChars = MAX_LINE_CHARS): CWord[][] {
  const lines: CWord[][] = []
  let cur: CWord[] = []
  for (const w of words) {
    if (cur.length) {
      const prev = cur[cur.length - 1]
      const chars = cur.reduce((a, x) => a + x.w.length, 0) + cur.length + w.w.length
      if (
        cur.length >= wordsPerLine ||
        BREAK_PUNCT.some((p) => prev.w.endsWith(p)) ||
        w.s - prev.e > LINE_BREAK_PAUSE_S ||
        chars > maxChars
      ) {
        lines.push(cur)
        cur = []
      }
    }
    cur.push(w)
  }
  if (cur.length) lines.push(cur)
  return lines
}

export function captionSpans(words: CWord[], wordsPerLine: number, animation: string, duration: number): Span[] {
  const lines = groupLines(words, Math.max(1, wordsPerLine))
  const spans: Span[] = []
  lines.forEach((line, li) => {
    const nxt = li + 1 < lines.length ? lines[li + 1][0].s : null
    const lastE = line[line.length - 1].e
    let lineEnd = nxt !== null && nxt - lastE <= HOLD_GAP_S + 1e-9 ? nxt : lastE + HOLD_AFTER_S
    if (nxt !== null) lineEnd = Math.min(lineEnd, nxt)
    lineEnd = round3(Math.min(lineEnd, duration))
    const lineStart = line[0].s
    if (lineEnd <= lineStart) return
    const texts = line.map((w) => w.w)
    if (animation === 'none') {
      spans.push({ s: lineStart, e: lineEnd, line: texts, current: null })
      return
    }
    line.forEach((w, wi) => {
      const s = wi === 0 ? lineStart : w.s
      const e = wi + 1 < line.length ? line[wi + 1].s : lineEnd
      if (e > s) spans.push({ s, e, line: texts, current: wi })
    })
  })
  return spans
}

/** Span visível no tempo relativo t (busca binária; spans são ordenados e não se sobrepõem). */
export function spanAt(spans: Span[], t: number): Span | null {
  let lo = 0
  let hi = spans.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (spans[mid].e <= t) lo = mid + 1
    else if (spans[mid].s > t) hi = mid - 1
    else return spans[mid]
  }
  return null
}
