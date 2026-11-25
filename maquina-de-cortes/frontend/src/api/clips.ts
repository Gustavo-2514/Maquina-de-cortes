import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './client'
import { jobsKey, upsertJob } from './jobs'
import type { Clip, ClipReview, CostEstimate, Job, Platform, PostPack, ScoreBreakdown, Template } from './types'

export const clipsKey = (projectId: number) => ['clips', projectId] as const

export const useClips = (projectId: number, enabled = true) =>
  useQuery({ queryKey: clipsKey(projectId), queryFn: () => api<Clip[]>(`/projects/${projectId}/clips`), enabled })

export function upsertClip(list: Clip[] | undefined, c: Clip): Clip[] {
  if (!list) return [c]
  const i = list.findIndex((x) => x.id === c.id)
  if (i === -1) return [...list, c]
  if (list[i].updated_at > c.updated_at) return list
  const copy = list.slice()
  copy[i] = c
  return copy
}

export function parseBreakdown(c: Clip): ScoreBreakdown {
  try {
    return JSON.parse(c.score_breakdown_json || '{}')
  } catch {
    return {}
  }
}

export function useClipActions(projectId: number) {
  const qc = useQueryClient()
  const put = (c: Clip) => qc.setQueryData<Clip[]>(clipsKey(projectId), (old) => upsertClip(old, c))
  return {
    update: useMutation({
      mutationFn: ({ id, ...patch }: Partial<Clip> & { id: number }) =>
        api<Clip>(`/clips/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
      onSuccess: put,
    }),
    create: useMutation({
      mutationFn: (body: { start_s: number; end_s: number; title?: string }) => post<Clip>(`/projects/${projectId}/clips`, body),
      onSuccess: put,
    }),
    duplicate: useMutation({ mutationFn: (id: number) => post<Clip>(`/clips/${id}/duplicate`), onSuccess: put }),
    render: useMutation({
      mutationFn: (id: number) => post<Job>(`/clips/${id}/render`),
      onSuccess: (j) => qc.setQueryData<Job[]>(jobsKey, (old) => upsertJob(old, j)),
    }),
    renderAll: useMutation({
      mutationFn: () => post<Job[]>(`/projects/${projectId}/render-all`),
      onSuccess: (js) => qc.setQueryData<Job[]>(jobsKey, (old) => js.reduce((acc, j) => upsertJob(acc, j), old ?? [])),
    }),
    postPack: useMutation({
      mutationFn: ({ id, texts, cover }: { id: number; texts: boolean; cover: boolean }) =>
        post<Job>(`/clips/${id}/post-pack`, { texts, cover }),
      onSuccess: (j) => qc.setQueryData<Job[]>(jobsKey, (old) => upsertJob(old, j)),
    }),
    postPackAll: useMutation({
      mutationFn: () => post<Job[]>(`/projects/${projectId}/post-pack`, { only_missing: true }),
      onSuccess: (js) => qc.setQueryData<Job[]>(jobsKey, (old) => js.reduce((acc, j) => upsertJob(acc, j), old ?? [])),
    }),
    review: useMutation({
      mutationFn: ({ id, model }: { id: number; model: string }) => post<Job>(`/clips/${id}/review`, { model }),
      onSuccess: (j) => qc.setQueryData<Job[]>(jobsKey, (old) => upsertJob(old, j)),
    }),
    reviewAll: useMutation({
      mutationFn: (model: string) => post<Job[]>(`/projects/${projectId}/review`, { model, only_missing: true }),
      onSuccess: (js) => qc.setQueryData<Job[]>(jobsKey, (old) => js.reduce((acc, j) => upsertJob(acc, j), old ?? [])),
    }),
    savePost: useMutation({
      mutationFn: ({ id, ...texts }: Required<Pick<PostPack, Platform>> & { id: number }) =>
        api<Clip>(`/clips/${id}/post`, { method: 'PUT', body: JSON.stringify(texts) }),
      onSuccess: put,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<{ ok: boolean }>(`/clips/${id}`, { method: 'DELETE' }),
      onSuccess: (_r, id) => qc.setQueryData<Clip[]>(clipsKey(projectId), (old) => old?.filter((c) => c.id !== id)),
    }),
  }
}

export const clipFileUrl = (id: number, download = false) => `/api/clips/${id}/file${download ? '?download=1' : ''}`
export const clipPreviewUrl = (c: Clip) =>
  `/api/media/projects/${c.project_id}/clips/${c.id}/preview.jpg?v=${encodeURIComponent(c.rendered_at ?? '')}`

export function parsePost(c: Clip): PostPack {
  try {
    const p = JSON.parse(c.post_json || '{}')
    return p && typeof p === 'object' ? p : {}
  } catch {
    return {}
  }
}

export const hasPostTexts = (p: PostPack) => !!(p.tiktok || p.reels || p.shorts)

export const PLATFORM_LABELS: Record<Platform, string> = { tiktok: 'TikTok', reels: 'Reels', shorts: 'Shorts' }

export const tagsLine = (tags: string[], extra: string[] = []) => [...tags, ...extra].map((t) => `#${t}`).join(' ')

/** Texto pronto para colar na plataforma (igual ao textos.txt do .zip). */
export function platformText(p: PostPack, k: Platform): string {
  if (k === 'shorts') {
    const s = p.shorts
    return s ? [s.description, tagsLine(s.hashtags, ['Shorts'])].filter(Boolean).join('\n\n') : ''
  }
  const x = p[k]
  return x ? [x.caption, tagsLine(x.hashtags)].filter(Boolean).join('\n\n') : ''
}

/** "#um dois, #três" → ["um", "dois", "três"] (o backend normaliza acentos e limites). */
export const parseTags = (s: string) =>
  s
    .split(/[\s,]+/)
    .map((t) => t.replace(/^#+/, ''))
    .filter(Boolean)

export const coverUrl = (c: Clip, titled = false, download = false) => {
  const p = parsePost(c)
  const q = new URLSearchParams({ v: p.cover_at ?? '' })
  if (titled) q.set('titled', '1')
  if (download) q.set('download', '1')
  return `/api/clips/${c.id}/cover?${q}`
}

export const exportZipUrl = (projectId: number) => `/api/projects/${projectId}/export.zip`

export const useTemplates = () =>
  useQuery({ queryKey: ['templates'], queryFn: () => api<Template[]>('/templates'), staleTime: Infinity })

export function useApplyTemplate(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { template: string; render: boolean }) =>
      post<{ ok: boolean; clips: number; renders: number }>(`/projects/${projectId}/apply-template`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clipsKey(projectId) })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
}

export const REFRAME_LABELS: Record<Clip['reframe_mode'], string> = {
  auto: 'Seguir rosto',
  speaker: 'Quem fala no centro',
  center: 'Centro',
  blur_fit: 'Inteiro + fundo borrado',
  split: 'Tela dividida',
  gameplay: 'Webcam + jogo',
  manual: 'Manual',
}

export function parseReview(c: Clip): ClipReview {
  try {
    return JSON.parse(c.review_json || '{}') as ClipReview
  } catch {
    return {}
  }
}

/** A revisão vale para o MP4 atual? (re-render invalida) */
export const reviewIsCurrent = (c: Clip, r: ClipReview = parseReview(c)) => !!r.verdict && r.rendered_at === c.rendered_at

export interface ProjectReviewEstimate extends CostEstimate {
  clips: number
  clip_ids: number[]
  per_clip_usd: (number | null)[]
}

export const useReviewEstimate = (projectId: number, model: string, enabled: boolean) =>
  useQuery({
    queryKey: ['review-estimate', projectId, model],
    queryFn: () => api<ProjectReviewEstimate>(`/projects/${projectId}/review-estimate?model=${encodeURIComponent(model)}`),
    enabled,
    retry: false,
  })

export const useClipReviewEstimate = (clipId: number, model: string, enabled: boolean) =>
  useQuery({
    queryKey: ['clip-review-estimate', clipId, model],
    queryFn: () => api<CostEstimate>(`/clips/${clipId}/review-estimate?model=${encodeURIComponent(model)}`),
    enabled,
    retry: false,
  })
