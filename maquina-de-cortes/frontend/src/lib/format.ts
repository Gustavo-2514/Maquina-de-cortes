export function formatDuration(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—'
  const t = Math.round(s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = t % 60
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i >= 2 ? 1 : 0)} ${units[i]}`
}

/** Datas do backend vêm em UTC (ISO, às vezes sem 'Z'). */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
}

const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' })

export function formatRelative(iso: string | null | undefined): string {
  const d = parseDate(iso)
  if (!d) return ''
  const diff = (d.getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 60) return rtf.format(Math.round(diff), 'second')
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  return rtf.format(Math.round(diff / 86400), 'day')
}

export function elapsed(startIso: string | null, endIso: string | null): string {
  const a = parseDate(startIso)
  if (!a) return '—'
  const b = parseDate(endIso) ?? new Date()
  return formatDuration((b.getTime() - a.getTime()) / 1000)
}

export const FORMAT_LABELS = { best: 'Melhor', '1080p': '1080p', '720p': '720p', audio_mp3: 'Só áudio (MP3)' } as const

export const JOB_TYPE_LABELS: Record<string, string> = {
  download: 'Download',
  probe_proxy: 'Preparar vídeo',
  transcribe: 'Transcrição',
  analyze: 'Análise (IA)',
  reframe: 'Análise de rostos',
  render: 'Render',
}
