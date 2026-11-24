import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { downloadsKey, upsertDownload } from './downloads'
import { jobsKey, upsertJob } from './jobs'
import { projectKey, projectsKey, transcriptKey, upsertProject } from './projects'
import { clipsKey, upsertClip } from './clips'
import type { Clip, Download, Job, Project } from './types'

/** Assina GET /api/events (SSE) e aplica as mudanças direto no cache do TanStack Query. */
export function useServerEvents() {
  const qc = useQueryClient()
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const es = new EventSource('/api/events')
    let wasDisconnected = false

    es.onopen = () => {
      setConnected(true)
      // eventos podem ter sido perdidos enquanto desconectado
      if (wasDisconnected) qc.invalidateQueries()
      wasDisconnected = false
    }
    es.onerror = () => {
      setConnected(false)
      wasDisconnected = true
    }
    es.addEventListener('job.update', (e) => {
      const job = JSON.parse((e as MessageEvent).data) as Job
      qc.setQueryData<Job[]>(jobsKey, (old) => (old ? upsertJob(old, job) : old))
    })
    es.addEventListener('download.update', (e) => {
      const d = JSON.parse((e as MessageEvent).data) as Download
      qc.setQueryData<Download[]>(downloadsKey, (old) => (old ? upsertDownload(old, d) : old))
    })
    es.addEventListener('project.update', (e) => {
      const p = JSON.parse((e as MessageEvent).data) as Project
      qc.setQueryData<Project[]>(projectsKey, (old) => (old ? upsertProject(old, p) : old))
      const prev = qc.getQueryData<Project>(projectKey(p.id))
      if (!prev || prev.updated_at <= p.updated_at) qc.setQueryData(projectKey(p.id), p)
      // análise terminou → buscar transcrição e a lista nova de cortes (a reanálise apaga sugestões antigas)
      if (p.status === 'ready' && prev?.status !== 'ready') {
        qc.invalidateQueries({ queryKey: ['project-files', p.id] })
        qc.invalidateQueries({ queryKey: transcriptKey(p.id) })
        qc.invalidateQueries({ queryKey: clipsKey(p.id) })
      }
      if (p.stage === 'analyze' && prev?.stage !== 'analyze') qc.invalidateQueries({ queryKey: transcriptKey(p.id) })
    })
    es.addEventListener('clip.update', (e) => {
      const c = JSON.parse((e as MessageEvent).data) as Clip
      qc.setQueryData<Clip[]>(clipsKey(c.project_id), (old) => (old ? upsertClip(old, c) : old))
      const prevClip = qc.getQueryData<Clip>(['clip', c.id])
      if (prevClip && prevClip.updated_at <= c.updated_at) qc.setQueryData(['clip', c.id], c)
    })
    return () => es.close()
  }, [qc])

  return connected
}
