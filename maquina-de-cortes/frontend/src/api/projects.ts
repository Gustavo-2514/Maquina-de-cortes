import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, post } from './client'
import { downloadsKey } from './downloads'
import type { AnalysisOptions, CostEstimate, Download, Project, ProjectAiCost, Transcript } from './types'

export const projectsKey = ['projects'] as const
export const projectKey = (id: number) => ['project', id] as const
export const transcriptKey = (id: number) => ['transcript', id] as const

export const useProjects = () => useQuery({ queryKey: projectsKey, queryFn: () => api<Project[]>('/projects') })

export const useProject = (id: number) =>
  useQuery({ queryKey: projectKey(id), queryFn: () => api<Project>(`/projects/${id}`), enabled: Number.isFinite(id) })

export const useTranscript = (id: number, enabled: boolean) =>
  useQuery({
    queryKey: transcriptKey(id),
    queryFn: () => api<Transcript>(`/projects/${id}/transcript`),
    enabled,
    retry: false,
  })

export function upsertProject(list: Project[] | undefined, p: Project): Project[] {
  if (!list) return [p]
  const i = list.findIndex((x) => x.id === p.id)
  if (i === -1) return [p, ...list].sort((a, b) => b.id - a.id)
  if (list[i].updated_at > p.updated_at) return list
  const copy = list.slice()
  copy[i] = p
  return copy
}

export const DEFAULT_ANALYSIS: AnalysisOptions = {
  num_clips: 10,
  min_s: 60,
  max_s: 90,
  extra_prompt: '',
  language: 'pt',
  caption_style: 'hormozi',
  reframe_mode: 'auto',
  template: 'geral',
  llm: 'ollama',
}

export function parseOptions(p: Project): AnalysisOptions {
  try {
    return { ...DEFAULT_ANALYSIS, language: p.language, ...JSON.parse(p.settings_json || '{}') }
  } catch {
    return { ...DEFAULT_ANALYSIS, language: p.language }
  }
}

/** Upload em streaming com progresso (XHR — fetch não expõe progresso de envio). */
export function uploadProject(file: File, name: string, onProgress: (pct: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const qs = new URLSearchParams({ filename: file.name, name })
    xhr.open('POST', `/api/projects/upload?${qs}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((100 * e.loaded) / e.total)
    xhr.onload = () => {
      let body: unknown
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        body = undefined
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Project)
      else {
        const d = body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : `Erro ${xhr.status}`
        reject(new ApiError(xhr.status, d, body))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Falha de rede no upload'))
    xhr.send(file)
  })
}

export function useProjectActions() {
  const qc = useQueryClient()
  const put = (p: Project) => {
    qc.setQueryData<Project[]>(projectsKey, (old) => (old ? upsertProject(old, p) : old))
    qc.setQueryData(projectKey(p.id), p)
  }
  return {
    put,
    fromDownload: useMutation({
      mutationFn: (downloadId: number) => post<Project>(`/downloads/${downloadId}/to-project`),
      onSuccess: (p) => {
        put(p)
        qc.setQueryData<Download[]>(downloadsKey, (old) => old?.map((d) => (d.id === p.download_id ? { ...d, project_id: p.id } : d)))
      },
    }),
    create: useMutation({
      mutationFn: (body: { download_id?: number; local_path?: string; name?: string; language?: string }) => post<Project>('/projects', body),
      onSuccess: put,
    }),
    analyze: useMutation({
      mutationFn: ({ id, options }: { id: number; options: AnalysisOptions }) => post<Project>(`/projects/${id}/analyze`, options),
      onSuccess: (p) => {
        put(p)
        qc.invalidateQueries({ queryKey: transcriptKey(p.id) })
      },
    }),
    rename: useMutation({
      mutationFn: ({ id, name }: { id: number; name: string }) =>
        api<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
      onSuccess: put,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<{ ok: boolean }>(`/projects/${id}`, { method: 'DELETE' }),
      onSuccess: (_r, id) => {
        qc.setQueryData<Project[]>(projectsKey, (old) => old?.filter((p) => p.id !== id))
        qc.removeQueries({ queryKey: projectKey(id) })
        qc.invalidateQueries({ queryKey: downloadsKey })
        qc.invalidateQueries({ queryKey: ['jobs'] })
      },
    }),
    saveTranscript: useMutation({
      mutationFn: ({ id, transcript }: { id: number; transcript: Transcript }) =>
        api<Transcript>(`/projects/${id}/transcript`, { method: 'PUT', body: JSON.stringify(transcript) }),
      onSuccess: (t, { id }) => qc.setQueryData(transcriptKey(id), t),
    }),
  }
}

export const mediaUrl = (projectId: number, file: string) => `/api/media/projects/${projectId}/${file}`

export interface Estimate {
  total_seconds: number
  gpu: boolean
  stages: { key: string; label: string; seconds: number; cached: boolean }[]
  claude: { configured: boolean; from_transcript: boolean; prices_as_of: string; models: CostEstimate[] }
}

export const useEstimate = (id: number, language: string, enabled: boolean, numClips = 10, template = 'geral') =>
  useQuery({
    queryKey: ['estimate', id, language, numClips, template],
    queryFn: () =>
      api<Estimate>(
        `/projects/${id}/estimate?${new URLSearchParams({ language, num_clips: String(numClips), template })}`,
      ),
    enabled,
    retry: false,
    staleTime: 30_000,
  })

export const useProjectFiles = (id: number, enabled = true) =>
  useQuery({
    queryKey: ['project-files', id],
    queryFn: () => api<Record<'proxy' | 'audio' | 'waveform' | 'thumbs' | 'transcript' | 'faces', boolean>>(`/projects/${id}/files`),
    enabled,
  })

export function usePrepareMedia(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<Project>(`/projects/${id}/prepare`),
    onSuccess: (p) => {
      qc.setQueryData(projectKey(p.id), p)
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function parseAiCost(p: Project): ProjectAiCost {
  try {
    return JSON.parse(p.ai_cost_json || '{}') as ProjectAiCost
  } catch {
    return {}
  }
}
