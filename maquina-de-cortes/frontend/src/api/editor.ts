import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { CropTrack } from '@/lib/crop'
import { api, ApiError, post } from './client'
import type { CaptionStyle, Clip } from './types'

export const useClip = (id: number) =>
  useQuery({ queryKey: ['clip', id], queryFn: () => api<Clip>(`/clips/${id}`), enabled: Number.isFinite(id), staleTime: Infinity })

export const useCaptionStyles = () =>
  useQuery({ queryKey: ['caption-styles'], queryFn: () => api<CaptionStyle[]>('/caption-styles'), staleTime: 60_000 })

export function useCreateStyle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Omit<CaptionStyle, 'id' | 'key' | 'is_builtin'>) => post<CaptionStyle>('/caption-styles', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['caption-styles'] }),
  })
}

export function useDeleteStyle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/caption-styles/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['caption-styles'] }),
  })
}

export const useWaveform = (projectId: number) =>
  useQuery({
    queryKey: ['waveform', projectId],
    queryFn: () => api<{ rate: number; length: number; peaks: number[] }>(`/projects/${projectId}/waveform`),
    staleTime: Infinity,
    retry: false,
  })

export const useThumbs = (projectId: number) =>
  useQuery({
    queryKey: ['thumbs', projectId],
    queryFn: () => api<{ every_s: number; urls: string[] }>(`/projects/${projectId}/thumbs`),
    staleTime: Infinity,
  })

/**
 * Trilha de crop do servidor para o modo/intervalo salvos. `signature` muda quando o corte salvo muda
 * (início/fim/modo/keyframes); o preview mantém a trilha anterior enquanto a nova carrega.
 */
export const useCropTrack = (clipId: number, signature: string, enabled: boolean) =>
  useQuery({
    queryKey: ['crop-track', clipId, signature],
    queryFn: async () => {
      try {
        return await api<CropTrack>(`/clips/${clipId}/crop-track?fps=10`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) return null // análise de rostos ainda rodando
        throw e
      }
    },
    enabled,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
