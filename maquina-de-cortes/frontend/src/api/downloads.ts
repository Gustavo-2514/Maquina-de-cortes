import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './client'
import type { AnalysisOptions, Download, FormatChoice, LinkInfo } from './types'

export const downloadsKey = ['downloads'] as const

export const useDownloads = () =>
  useQuery({ queryKey: downloadsKey, queryFn: () => api<Download[]>('/downloads') })

export const fetchLinkInfo = (url: string) => post<LinkInfo>('/downloads/info', { url })

export interface NewDownload {
  url: string
  format_choice: FormatChoice
  send_to_project: boolean
  title?: string
  uploader?: string
  duration_s?: number | null
  thumbnail_url?: string
  /** opções da análise do projeto criado ao terminar (só com send_to_project) */
  analyze?: Partial<AnalysisOptions>
}

/** Insere/atualiza um download na lista em cache (usado pela resposta da API e pelo SSE). */
export function upsertDownload(list: Download[] | undefined, d: Download): Download[] {
  if (!list) return [d]
  const i = list.findIndex((x) => x.id === d.id)
  if (i === -1) return [d, ...list].sort((a, b) => b.id - a.id)
  if (list[i].updated_at > d.updated_at) return list // evento atrasado
  const copy = list.slice()
  copy[i] = d
  return copy
}

export function useDownloadActions() {
  const qc = useQueryClient()
  const put = (d: Download) => qc.setQueryData<Download[]>(downloadsKey, (old) => upsertDownload(old, d))

  return {
    create: useMutation({
      mutationFn: (items: NewDownload[]) => post<Download[]>('/downloads/batch', { items }),
      onSuccess: (ds) => ds.forEach(put),
    }),
    cancel: useMutation({ mutationFn: (id: number) => post<Download>(`/downloads/${id}/cancel`), onSuccess: put }),
    retry: useMutation({ mutationFn: (id: number) => post<Download>(`/downloads/${id}/retry`), onSuccess: put }),
    remove: useMutation({
      mutationFn: ({ id, deleteFile }: { id: number; deleteFile: boolean }) =>
        api<{ ok: boolean; file_removed: boolean }>(`/downloads/${id}?delete_file=${deleteFile}`, { method: 'DELETE' }),
      onSuccess: (_r, { id }) => {
        qc.setQueryData<Download[]>(downloadsKey, (old) => old?.filter((d) => d.id !== id))
        qc.invalidateQueries({ queryKey: ['jobs'] })
      },
    }),
  }
}

export const openFolder = (path: string) => post<{ ok: boolean }>('/system/open-folder', { path })
