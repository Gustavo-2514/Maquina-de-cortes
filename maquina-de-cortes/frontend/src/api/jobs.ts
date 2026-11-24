import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './client'
import type { Job } from './types'

export const jobsKey = ['jobs'] as const

export const useJobs = () => useQuery({ queryKey: jobsKey, queryFn: () => api<Job[]>('/jobs') })

export function upsertJob(list: Job[] | undefined, j: Job): Job[] {
  if (!list) return [j]
  const i = list.findIndex((x) => x.id === j.id)
  if (i === -1) return [j, ...list].sort((a, b) => b.id - a.id)
  if (list[i].updated_at > j.updated_at) return list
  const copy = list.slice()
  // respostas de cancelar/repetir não trazem o nome do alvo: mantém o que já tínhamos
  copy[i] = { ...j, target: j.target ?? list[i].target, target_link: j.target_link ?? list[i].target_link }
  return copy
}

export function useJobActions() {
  const qc = useQueryClient()
  const put = (j: Job) => qc.setQueryData<Job[]>(jobsKey, (old) => upsertJob(old, j))
  return {
    cancel: useMutation({ mutationFn: (id: number) => post<Job>(`/jobs/${id}/cancel`), onSuccess: put }),
    retry: useMutation({ mutationFn: (id: number) => post<Job>(`/jobs/${id}/retry`), onSuccess: put }),
  }
}
