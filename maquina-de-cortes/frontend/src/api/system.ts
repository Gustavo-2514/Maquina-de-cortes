import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post } from './client'
import type { AiCost } from './types'

export interface CheckItem {
  key: string
  label: string
  ok: boolean
  detail: string
  fix: string
  optional: boolean
}

export interface SystemCheck {
  ok: boolean
  items: CheckItem[]
  hardware: { cuda: boolean; gpu_name: string | null; vram_mb: number | null; nvenc: boolean }
  recommended: {
    whisper: { model: string; device: string; compute_type: string }
    encoder: string
    ollama_model: string
  }
}

export const useSystemCheck = () =>
  useQuery({
    queryKey: ['system', 'check'],
    queryFn: () => api<SystemCheck>('/system/check'),
    staleTime: 60_000,
  })

export interface UserSettings {
  whisper_model: string
  whisper_device: 'auto' | 'cuda' | 'cpu'
  whisper_compute_type: string
  ollama_url: string
  ollama_model: string
  encoder: 'auto' | 'nvenc' | 'x264'
  export_dir: string
  default_language: string
  cookies_path: string
  normalize_audio: boolean
  /** mascarada (••••1234) quando vem do servidor; enviar mascarada = manter a salva */
  anthropic_api_key: string
  /** legado: modelo da revisão antes de `review_model` */
  claude_model: string
  /** chave por provedor (openai, gemini, openrouter…); mascaradas como a da Anthropic */
  api_keys: Record<string, string>
  /** provedor "custom": base URL de uma API compatível com a OpenAI */
  custom_base_url: string
  ai_models: AiModelEntry[]
  /** ref do modelo padrão da revisão visual */
  review_model: string
}

/** Modelo adicionado pelo usuário (UserSettings.ai_models). Preços em US$ por milhão de tokens; null = desconhecido. */
export interface AiModelEntry {
  provider: string
  id: string
  label: string
  input_per_mtok: number | null
  output_per_mtok: number | null
  vision: boolean
  prices_as_of: string
}

export const useUserSettings = () =>
  useQuery({ queryKey: ['system', 'settings'], queryFn: () => api<UserSettings>('/system/settings') })

export function useSaveSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (s: UserSettings) => api<UserSettings>('/system/settings', { method: 'PUT', body: JSON.stringify(s) }),
    onSuccess: (s) => {
      qc.setQueryData(['system', 'settings'], s)
      qc.invalidateQueries({ queryKey: ['system', 'ai-models'] })
      qc.invalidateQueries({ queryKey: ['system', 'ai-providers'] })
      qc.invalidateQueries({ queryKey: ['estimate'] })
    },
  })
}

export const useYtdlpVersion = () =>
  useQuery({ queryKey: ['system', 'ytdlp'], queryFn: () => api<{ version: string }>('/system/ytdlp') })

export function useUpdateYtdlp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<{ version: string; restart_required: boolean }>('/system/update-ytdlp'),
    onSuccess: (r) => qc.setQueryData(['system', 'ytdlp'], { version: r.version }),
  })
}

export const useWhisperModels = () =>
  useQuery({ queryKey: ['system', 'whisper-models'], queryFn: () => api<{ models: string[] }>('/system/whisper-models'), staleTime: Infinity })

export const useOllamaModels = (url: string) =>
  useQuery({
    queryKey: ['system', 'ollama-models', url],
    queryFn: () => api<{ models: { name: string; size: number }[] }>(`/system/ollama/models?url=${encodeURIComponent(url)}`),
    enabled: !!url,
    retry: false,
  })

export const testOllama = (url: string, model: string) =>
  post<{ ok: boolean; reply: string; seconds: number }>('/system/ollama/test', { url, model })

export interface StorageReport {
  data_dir: string
  free_bytes: number
  total_bytes: number
  folders: Record<'downloads' | 'projects' | 'exports' | 'logs', number>
  cleanable: Record<'temp' | 'audio' | 'proxies', { bytes: number; count: number; projects: number[] }>
  proxy_days: number
}

export const useStorage = (proxyDays: number) =>
  useQuery({ queryKey: ['system', 'storage', proxyDays], queryFn: () => api<StorageReport>(`/system/storage?proxy_days=${proxyDays}`) })

export function useCleanup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { temp: boolean; audio: boolean; proxies: boolean; proxy_days: number }) =>
      post<{ freed_bytes: number; removed: number }>('/system/cleanup', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['system', 'storage'] })
      qc.invalidateQueries({ queryKey: ['project-files'] })
    },
  })
}

export interface AiProvider {
  key: string
  label: string
  base_url: string
  env: string
  key_hint: string
  keys_url: string
  vision_default: boolean
  configured: boolean
}

export const useAiProviders = () =>
  useQuery({ queryKey: ['system', 'ai-providers'], queryFn: () => api<{ providers: AiProvider[] }>('/system/ai/providers') })

/** Modelo pago selecionável (Claude embutido + adicionados). `ref` é o valor usado em `llm` e na revisão. */
export interface AiModel {
  ref: string
  provider: string
  provider_label: string
  id: string
  label: string
  input_per_mtok: number | null
  output_per_mtok: number | null
  vision: boolean
  prices_as_of: string
  configured: boolean
  priced: boolean
}

export const useAiModels = () =>
  useQuery({ queryKey: ['system', 'ai-models'], queryFn: () => api<{ default_review: string; models: AiModel[] }>('/system/ai/models') })

export interface CatalogModel {
  id: string
  label: string
  input_per_mtok: number | null
  output_per_mtok: number | null
  vision: boolean
  context?: number | null
  prices_as_of: string
}

export const useAiCatalog = (provider: string, enabled: boolean) =>
  useQuery({
    queryKey: ['system', 'ai-catalog', provider],
    queryFn: () => api<{ provider: string; models: CatalogModel[] }>(`/system/ai/catalog?provider=${encodeURIComponent(provider)}`),
    enabled: enabled && !!provider,
    retry: false,
    staleTime: 10 * 60_000,
  })

/** Valida a chave sem custo (lista modelos / consulta a chave no provedor). */
export const testAiKey = (provider: string, api_key: string, base_url = '') =>
  post<{ ok: boolean; message: string; detail?: string }>('/system/ai/test', { provider, api_key, base_url })

export interface ClaudeModel {
  id: string
  label: string
  input_per_mtok: number
  output_per_mtok: number
}

/** Lista local usada enquanto o backend não responde (ex.: app antigo ainda rodando). Preços: só os do backend. */
export const CLAUDE_MODELS_FALLBACK: ClaudeModel[] = [
  { id: 'claude-opus-5-5', label: 'Claude Opus 5.5 (melhor qualidade)', input_per_mtok: 0, output_per_mtok: 0 },
  { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5 (equilíbrio)', input_per_mtok: 0, output_per_mtok: 0 },
  { id: 'claude-haiku-5-5', label: 'Claude Haiku 5.5 (mais barato)', input_per_mtok: 0, output_per_mtok: 0 },
]

export const useClaudeModels = () =>
  useQuery({
    queryKey: ['system', 'claude-models'],
    queryFn: () => api<{ default: string; prices_as_of: string; models: ClaudeModel[] }>('/system/claude/models'),
    staleTime: Infinity,
  })

export const testClaude = (api_key: string, model: string) =>
  post<{ ok: boolean; message: string; detail?: string; cost?: AiCost }>('/system/claude/test', { api_key, model })
