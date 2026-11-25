export type DownloadStatus = 'queued' | 'downloading' | 'done' | 'error' | 'canceled'
export type FormatChoice = 'best' | '1080p' | '720p' | 'audio_mp3'

export interface Download {
  id: number
  url: string
  title: string
  uploader: string
  duration_s: number | null
  thumbnail_url: string
  format_choice: FormatChoice
  status: DownloadStatus
  progress: number
  speed: string
  eta: string
  file_path: string
  filesize: number | null
  error: string
  error_detail: string
  send_to_project: boolean
  project_id: number | null
  created_at: string
  updated_at: string
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error' | 'canceled'

export interface Job {
  id: number
  type: string
  ref_id: number
  status: JobStatus
  progress: number
  message: string
  error: string
  error_detail: string
  uses_gpu: boolean
  priority: number
  params_json?: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
  target?: string
  target_link?: string
}

export interface VideoInfo {
  kind: 'video'
  url: string
  title: string
  uploader: string
  duration_s: number | null
  thumbnail_url: string
  is_live: boolean
  heights: number[]
}

export interface PlaylistEntry {
  url: string
  title: string
  duration_s: number | null
  thumbnail_url: string
  uploader: string
}

export interface PlaylistInfo {
  kind: 'playlist'
  url: string
  title: string
  uploader: string
  entries: PlaylistEntry[]
}

export type LinkInfo = VideoInfo | PlaylistInfo

export type ProjectStatus = 'new' | 'processing' | 'ready' | 'error'
export type ProjectStage = 'probe' | 'proxy' | 'transcribe' | 'analyze' | 'done'

export interface Project {
  id: number
  name: string
  source_path: string
  origin: 'download' | 'upload' | 'local_path'
  download_id: number | null
  duration_s: number | null
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
  language: string
  status: ProjectStatus
  stage: ProjectStage
  progress: number
  error: string
  error_detail: string
  settings_json: string
  detected_language: string
  word_count: number
  faces_ready: boolean
  ai_cost_json: string
  created_at: string
  updated_at: string
}

export interface AnalysisOptions {
  num_clips: number
  min_s: number
  max_s: number
  extra_prompt: string
  language: string
  caption_style: string
  reframe_mode: 'auto' | 'speaker' | 'center' | 'blur_fit' | 'split' | 'gameplay'
  template: string
  /** 'ollama' (local, grátis) ou o id de um modelo do Claude (pago) */
  llm: string
}

export interface Template {
  key: string
  name: string
  description: string
  reframe_mode: AnalysisOptions['reframe_mode']
  caption_style: string
  caption_position_y: number | null
  caption_font_size: number | null
  tips: string[]
}

export interface Word {
  w: string
  s: number
  e: number
  p: number
}

export interface Segment {
  id: number
  start: number
  end: number
  text: string
  words: Word[]
}

export interface Transcript {
  language: string
  model?: string
  device?: string
  segments: Segment[]
}

export type ClipStatus = 'suggested' | 'edited' | 'rendering' | 'rendered' | 'error' | 'discarded'

export interface Clip {
  id: number
  project_id: number
  title: string
  hook_text: string
  reason: string
  start_s: number
  end_s: number
  score: number
  score_breakdown_json: string
  status: ClipStatus
  origin: 'ai' | 'manual'
  reframe_mode: 'auto' | 'speaker' | 'center' | 'blur_fit' | 'split' | 'gameplay' | 'manual'
  manual_crop_json: string
  layout_json: string
  caption_style_id: number | null
  caption_overrides_json: string
  export_json: string
  title_overlay: string
  post_json: string
  review_json: string
  output_path: string
  error: string
  rendered_at: string | null
  created_at: string
  updated_at: string
}

export type Platform = 'tiktok' | 'reels' | 'shorts'

/** Pacote para postar (Clip.post_json). */
export interface PostPack {
  tiktok?: { caption: string; hashtags: string[] }
  reels?: { caption: string; hashtags: string[] }
  shorts?: { title: string; description: string; hashtags: string[] }
  texts_at?: string
  edited_at?: string
  model?: string
  cover_t?: number
  cover_at?: string
  cover_title?: boolean
}

export interface ScoreBreakdown {
  gancho?: number
  emocao?: number
  clareza?: number
  completude?: number
  llm?: number
  heuristica?: number
  energia?: number
  ritmo?: number
  silencio?: number
  palavras_s?: number
}

export interface CaptionStyle {
  id: number
  key: string
  name: string
  font: string
  font_size: number
  primary_color: string
  highlight_color: string
  outline_color: string
  outline_px: number
  shadow_px: number
  uppercase: boolean
  words_per_line: number
  position_y: number
  animation: 'highlight' | 'pop' | 'karaoke' | 'none'
  is_builtin: boolean
}

/** Custo real de uma chamada paga (Claude), medido pelo backend a partir do `usage` da API. */
export interface AiCost {
  provider: 'claude' | 'claude-code'
  tokens_approx?: number
  models: string[]
  calls: number
  input_tokens: number
  output_tokens: number
  usd: number
  prices_as_of: string
}

/** Project.ai_cost_json */
export interface ProjectAiCost {
  analysis?: AiCost & { at: string }
  reviews_usd?: number
  total_usd?: number
}

export type ReviewVerdict = 'ok' | 'warn' | 'bad'

/** Clip.review_json — revisão visual pelo Claude */
export interface ClipReview {
  verdict?: ReviewVerdict
  summary?: string
  issues?: { t: number; kind: string; severity: 'leve' | 'grave'; text: string }[]
  model?: string
  cost?: AiCost
  at?: string
  rendered_at?: string | null
}

/** Estimativa de custo (antes de rodar) */
export interface CostEstimate {
  model: string
  label?: string
  calls: number
  input_tokens: number
  output_tokens: number
  usd: number
  max_usd?: number
  prices_as_of: string
  /** há chave da Anthropic (Configurações ou ANTHROPIC_API_KEY) */
  configured?: boolean
}
