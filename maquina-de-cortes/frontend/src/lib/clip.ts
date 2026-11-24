export function scoreVariant(score: number) {
  if (score >= 80) return 'bg-success/15 text-success border-success/30'
  if (score >= 60) return 'bg-warning/15 text-warning border-warning/30'
  return 'bg-muted text-muted-foreground'
}

/** mm:ss.d — precisão de décimo de segundo para os tempos do corte. */
export function formatTime(s: number) {
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`
}

export function parseTime(v: string): number | null {
  const t = v.trim().replace(',', '.')
  if (!t) return null
  const parts = t.split(':').map(Number)
  if (parts.some((n) => !Number.isFinite(n) || n < 0)) return null
  return parts.reduce((acc, n) => acc * 60 + n, 0)
}
