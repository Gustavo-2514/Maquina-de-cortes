import { CircleCheck, Loader2, Save, SlidersHorizontal, Zap } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox, Input, NativeSelect } from '@/components/ui/input'
import { CLAUDE_MODELS_FALLBACK, testClaude, testOllama, type UserSettings, useClaudeModels, useOllamaModels, useSaveSettings, useSystemCheck, useUserSettings, useWhisperModels } from '@/api/system'
import { LANGUAGES } from '@/lib/languages'
import { formatBytes, formatUsd } from '@/lib/format'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

/** Preferências do usuário (seção 9.6). Edita um rascunho local e salva tudo de uma vez. */
export function PreferencesCard() {
  const { data: saved } = useUserSettings()
  const { data: check } = useSystemCheck()
  const { data: whisper } = useWhisperModels()
  const save = useSaveSettings()
  const [draft, setDraft] = useState<UserSettings | null>(null)
  const s = draft ?? saved
  const { data: ollama, error: ollamaErr, isFetching: ollamaLoading } = useOllamaModels(s?.ollama_url ?? '')
  const [testing, setTesting] = useState(false)
  const [testingClaude, setTestingClaude] = useState(false)
  const { data: claudeModels } = useClaudeModels()
  if (!s) return null

  const set = <K extends keyof UserSettings>(k: K, v: UserSettings[K]) => setDraft({ ...s, [k]: v })
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved)
  const rec = check?.recommended

  const runTest = async () => {
    setTesting(true)
    try {
      const r = await testOllama(s.ollama_url, s.ollama_model)
      toast.success(`Ollama respondeu “${r.reply}” em ${r.seconds}s`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falhou')
    } finally {
      setTesting(false)
    }
  }

  const runClaudeTest = async () => {
    setTestingClaude(true)
    try {
      // o teste usa o Haiku (o mais barato): uma fração de centavo
      const r = await testClaude(s.anthropic_api_key, 'claude-haiku-5-5')
      if (r.ok) toast.success(`${r.message} O teste custou ${formatUsd(r.cost?.usd)}.`)
      else toast.error(r.message, { description: r.detail })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falhou')
    } finally {
      setTestingClaude(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SlidersHorizontal className="size-4" /> Preferências
        </CardTitle>
        <CardDescription>“Automático” escolhe pelo seu hardware{rec && ` (aqui: Whisper ${rec.whisper.model} na ${rec.whisper.device === 'cuda' ? 'GPU' : 'CPU'}, encoder ${rec.encoder})`}.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Transcrição (Whisper)</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Modelo" hint="Maior = mais preciso e mais lento.">
              <NativeSelect value={s.whisper_model} onChange={(e) => set('whisper_model', e.target.value)}>
                {(whisper?.models ?? ['auto']).map((m) => (
                  <option key={m} value={m}>
                    {m === 'auto' ? 'Automático' : m}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Dispositivo">
              <NativeSelect value={s.whisper_device} onChange={(e) => set('whisper_device', e.target.value as UserSettings['whisper_device'])}>
                <option value="auto">Automático</option>
                <option value="cuda">GPU (CUDA)</option>
                <option value="cpu">CPU</option>
              </NativeSelect>
            </Field>
            <Field label="Precisão" hint="int8 economiza memória.">
              <NativeSelect value={s.whisper_compute_type} onChange={(e) => set('whisper_compute_type', e.target.value)}>
                <option value="auto">Automática</option>
                <option value="float16">float16 (GPU)</option>
                <option value="int8_float16">int8_float16 (GPU)</option>
                <option value="int8">int8 (CPU)</option>
                <option value="float32">float32</option>
              </NativeSelect>
            </Field>
          </div>
        </section>

        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">IA local (Ollama)</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Endereço do Ollama">
              <Input value={s.ollama_url} onChange={(e) => set('ollama_url', e.target.value)} className="font-mono text-xs" />
            </Field>
            <Field
              label="Modelo"
              hint={ollamaErr ? 'Ollama não respondeu nesse endereço.' : ollamaLoading ? 'Buscando modelos…' : 'Instale outros com: ollama pull <modelo>'}
            >
              <div className="flex gap-2">
                <NativeSelect value={s.ollama_model} onChange={(e) => set('ollama_model', e.target.value)}>
                  {!ollama?.models.some((m) => m.name === s.ollama_model) && <option value={s.ollama_model}>{s.ollama_model} (não instalado)</option>}
                  {ollama?.models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name} · {formatBytes(m.size)}
                    </option>
                  ))}
                </NativeSelect>
                <Button variant="outline" onClick={runTest} disabled={testing} title="Pergunta algo simples ao modelo">
                  {testing ? <Loader2 className="animate-spin" /> : <Zap />} Testar
                </Button>
              </div>
            </Field>
          </div>
        </section>

        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Claude (opcional, pago)</h3>
          <p className="text-xs text-muted-foreground">
            Alternativa à IA local na análise e na revisão visual dos cortes. Cobra por uso na sua conta da Anthropic; o custo estimado
            aparece antes de cada ação e o custo real depois. Sem chave, nada é enviado.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Chave da API da Anthropic" hint="Fica só neste computador (data/settings.json). Vazio = usa ANTHROPIC_API_KEY do ambiente.">
              <div className="flex gap-2">
                <Input
                  type="password"
                  autoComplete="off"
                  value={s.anthropic_api_key}
                  onChange={(e) => set('anthropic_api_key', e.target.value)}
                  placeholder="sk-ant-…"
                  className="font-mono text-xs"
                />
                <Button
                  variant="outline"
                  onClick={runClaudeTest}
                  disabled={testingClaude || dirty}
                  title={dirty ? 'Salve antes de testar' : 'Pedido mínimo ao Claude Haiku (fração de centavo)'}
                >
                  {testingClaude ? <Loader2 className="animate-spin" /> : <Zap />} Testar
                </Button>
              </div>
            </Field>
            <Field label="Modelo padrão da revisão visual" hint={claudeModels ? `Preços de tabela de ${claudeModels.prices_as_of} (entrada / saída por milhão de tokens).` : undefined}>
              <NativeSelect value={s.claude_model} onChange={(e) => set('claude_model', e.target.value)}>
                {(claudeModels?.models ?? CLAUDE_MODELS_FALLBACK).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {claudeModels && ` · US$ ${m.input_per_mtok} / ${m.output_per_mtok}`}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
        </section>

        <section className="space-y-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Exportação e padrões</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Encoder de vídeo">
              <NativeSelect value={s.encoder} onChange={(e) => set('encoder', e.target.value as UserSettings['encoder'])}>
                <option value="auto">Automático</option>
                <option value="nvenc">NVENC (GPU NVIDIA)</option>
                <option value="x264">x264 (CPU)</option>
              </NativeSelect>
            </Field>
            <Field label="Idioma padrão dos vídeos">
              <NativeSelect value={s.default_language} onChange={(e) => set('default_language', e.target.value)}>
                {LANGUAGES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Pasta de exportação" hint="Vazio = data/exports">
              <Input value={s.export_dir} onChange={(e) => set('export_dir', e.target.value)} placeholder="/home/voce/Vídeos/Cortes" className="font-mono text-xs" />
            </Field>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox checked={s.normalize_audio} onChange={(e) => set('normalize_audio', e.target.checked)} />
            Normalizar o áudio dos cortes (−14 LUFS) por padrão
          </label>
        </section>

        <div className="flex items-center justify-end gap-3 border-t pt-4">
          {!dirty && saved && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <CircleCheck className="size-3.5 text-success" /> Salvo
            </span>
          )}
          {dirty && (
            <Button variant="ghost" onClick={() => setDraft(null)}>
              Descartar
            </Button>
          )}
          <Button
            disabled={!dirty || save.isPending}
            onClick={() =>
              save.mutate(s, {
                onSuccess: () => (setDraft(null), toast.success('Preferências salvas — valem para as próximas tarefas')),
                onError: (e) => toast.error(e.message),
              })
            }
          >
            {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Salvar preferências
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
