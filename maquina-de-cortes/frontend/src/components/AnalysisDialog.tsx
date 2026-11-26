import { CircleDollarSign, Clock, Loader2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Checkbox, Input, NativeSelect, Textarea } from '@/components/ui/input'
import { useCaptionStyles } from '@/api/editor'
import { TemplatePicker } from '@/components/TemplatePicker'
import { parseAiCost, parseOptions, useEstimate, useProjectActions } from '@/api/projects'
import { useUserSettings } from '@/api/system'
import { formatTokens, formatUsd } from '@/lib/format'
import type { AnalysisOptions, CostEstimate, Project } from '@/api/types'
import { LANGUAGES } from '@/lib/languages'
import { loadStartPrefs } from '@/lib/startPrefs'

/** [rótulo do provedor, modelos] na ordem em que o backend lista (Claude primeiro). */
function groupByProvider(models: CostEstimate[]): [string, CostEstimate[]][] {
  const out = new Map<string, CostEstimate[]>()
  for (const m of models) {
    const k = m.provider_label ?? 'IA paga'
    out.set(k, [...(out.get(k) ?? []), m])
  }
  return [...out]
}

function fmtEstimate(s: number) {
  if (s < 60) return `~${Math.max(5, Math.round(s / 5) * 5)} s`
  if (s < 3600) return `~${Math.round(s / 60)} min`
  return `~${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

export function AnalysisDialog({ project, open, onClose }: { project: Project; open: boolean; onClose: () => void }) {
  // projeto novo (ex.: arquivo enviado): parte do tipo de conteúdo escolhido na tela inicial
  const [opts, setOpts] = useState<AnalysisOptions>(() =>
    project.status === 'new' && (project.settings_json || '{}') === '{}' ? { ...parseOptions(project), ...loadStartPrefs() } : parseOptions(project),
  )
  const { analyze } = useProjectActions()
  const { data: est } = useEstimate(project.id, opts.language, open, opts.num_clips, opts.template)
  const { data: settings } = useUserSettings()
  const paid = opts.llm !== 'ollama'
  const cost = paid ? est?.ai.models.find((m) => m.model === opts.llm) : undefined
  const groups = groupByProvider(est?.ai.models ?? [])
  const lastCost = parseAiCost(project).analysis
  const { data: styles } = useCaptionStyles()
  const set = <K extends keyof AnalysisOptions>(k: K, v: AnalysisOptions[K]) => setOpts((o) => ({ ...o, [k]: v }))
  const invalid = opts.min_s >= opts.max_s || (paid && !cost?.configured)

  const submit = () =>
    analyze.mutate(
      { id: project.id, options: opts },
      {
        onSuccess: () => {
          toast.success('Análise na fila')
          onClose()
        },
        onError: (e) => toast.error(e.message),
      },
    )

  return (
    <Dialog open={open} onClose={onClose} title="Configurar análise" description={project.name} className="max-w-xl">
      <div className="space-y-4">
        <div className="space-y-1.5">
          <span className="text-sm font-medium">Tipo de vídeo (template)</span>
          <TemplatePicker
            value={opts.template}
            onChange={(t) => setOpts((o) => ({ ...o, template: t.key, reframe_mode: t.reframe_mode, caption_style: t.caption_style }))}
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Nº de cortes">
            <Input type="number" min={1} max={50} value={opts.num_clips} onChange={(e) => set('num_clips', Number(e.target.value))} />
          </Field>
          <Field label="Duração mín. (s)">
            <Input type="number" min={5} max={600} value={opts.min_s} onChange={(e) => set('min_s', Number(e.target.value))} />
          </Field>
          <Field label="Duração máx. (s)">
            <Input type="number" min={10} max={900} value={opts.max_s} onChange={(e) => set('max_s', Number(e.target.value))} />
          </Field>
        </div>
        {opts.min_s >= opts.max_s && <p className="text-xs text-destructive">A duração mínima precisa ser menor que a máxima.</p>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Idioma do vídeo">
            <NativeSelect value={opts.language} onChange={(e) => set('language', e.target.value)}>
              {LANGUAGES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Enquadramento padrão">
            <NativeSelect value={opts.reframe_mode} onChange={(e) => set('reframe_mode', e.target.value as AnalysisOptions['reframe_mode'])}>
              <option value="auto">Seguir rosto</option>
              <option value="speaker">Quem fala no centro</option>
              <option value="gameplay">Webcam em cima + jogo embaixo</option>
              <option value="split">Tela dividida (2 pessoas)</option>
              <option value="blur_fit">Vídeo inteiro + fundo borrado</option>
              <option value="center">Centro</option>
            </NativeSelect>
          </Field>
        </div>
        <Field label="Preset de legenda padrão">
          <NativeSelect value={opts.caption_style} onChange={(e) => set('caption_style', e.target.value)}>
            {(styles?.filter((st) => st.key) ?? [{ key: 'hormozi', name: 'Hormozi' }]).map((st) => (
              <option key={st.key} value={st.key}>
                {st.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field
          label="IA que escolhe os cortes"
          hint={
            paid
              ? `Paga: usa a sua chave do ${cost?.provider_label ?? 'provedor'}. O custo real aparece na Fila e no projeto ao terminar.`
              : 'Roda no seu computador, sem custo.'
          }
        >
          <NativeSelect value={opts.llm} onChange={(e) => set('llm', e.target.value)}>
            <option value="ollama">Local — {settings?.ollama_model ?? 'Ollama'} (grátis)</option>
            {!paid || cost ? null : <option value={opts.llm}>{opts.llm} (não está mais nas Configurações)</option>}
            {groups.map(([label, models]) => (
              <optgroup key={label} label={label}>
                {models.map((m) => (
                  <option key={m.model} value={m.model} disabled={!m.configured}>
                    {m.label?.split(' · ')[0]} · {m.usd == null ? 'preço não configurado' : `≈ ${formatUsd(m.usd)}`}
                    {!m.configured && ' (configure a chave em Configurações)'}
                  </option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
        </Field>
        {est && est.ai.models.every((m) => m.provider === 'anthropic') && (
          <p className="-mt-2 text-xs text-muted-foreground">
            Para usar GPT, Gemini ou qualquer modelo do OpenRouter, salve a chave e adicione o modelo em{' '}
            <Link to="/configuracoes" className="text-primary underline-offset-4 hover:underline" onClick={onClose}>
              Configurações → IA paga
            </Link>
            .
          </p>
        )}
        {paid && cost && (
          <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
            <div className="mb-1 flex items-center gap-1.5 text-sm font-medium">
              <CircleDollarSign className="size-4" /> Custo estimado: {cost.usd == null ? 'sem preço configurado' : `≈ ${formatUsd(cost.usd)}`}
              {cost.max_usd != null && <span className="font-normal text-muted-foreground">(até {formatUsd(cost.max_usd)} se precisar repetir)</span>}
            </div>
            <p className="text-muted-foreground">
              {cost.calls} chamada(s) · ~{formatTokens(cost.input_tokens)} tokens de entrada · ~{formatTokens(cost.output_tokens)} de saída
              (inclui o raciocínio). {est?.ai.from_transcript ? 'Calculado pela transcrição.' : 'Estimado pela duração — a transcrição ainda não existe.'}{' '}
              {cost.usd == null
                ? 'Informe o preço do modelo em Configurações para ver o valor em US$.'
                : `Preços de ${cost.prices_as_of || 'tabela'}; a fatura do ${cost.provider_label ?? 'provedor'} é a referência final.`}
            </p>
          </div>
        )}
        {lastCost && (
          <p className="text-xs text-muted-foreground">
            Última análise com IA paga neste projeto custou {formatUsd(lastCost.usd)}
            {lastCost.priced === false && ' (sem contar modelos sem preço)'} ({lastCost.models.join(', ')}).
          </p>
        )}
        <Field label="Instruções extras para a IA" hint="Ex.: foque nas partes engraçadas; evite falar de patrocinadores.">
          <Textarea value={opts.extra_prompt} onChange={(e) => set('extra_prompt', e.target.value)} rows={3} maxLength={2000} />
        </Field>
        {est && (
          <div className="rounded-md border p-3 text-xs">
            <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Clock className="size-4" /> Tempo estimado: {fmtEstimate(est.total_seconds)}
              {!est.gpu && <span className="font-normal text-warning">(sem GPU — mais lento)</span>}
            </div>
            <ul className="space-y-0.5 text-muted-foreground">
              {est.stages.map((st) => (
                <li key={st.key} className="flex justify-between gap-2">
                  <span>{st.label}</span>
                  <span className="tabular-nums">{st.cached ? 'já feito' : fmtEstimate(st.seconds)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
          Etapas: preparar o vídeo → transcrever (Whisper) → a IA {paid ? `escolhida (${cost?.provider_label ?? 'paga'}, pela internet)` : 'local'} escolhe os trechos e dá nota{opts.auto_render ? ' → renderizar os MP4' : ''}. Etapas já feitas são
          reaproveitadas. Reanalisar substitui as sugestões da IA, mas mantém cortes editados e manuais.
        </p>
        <label className="flex items-start gap-2.5 rounded-md border p-3">
          <Checkbox checked={opts.auto_render} onChange={(e) => set('auto_render', e.target.checked)} className="mt-0.5" />
          <span className="text-sm">
            <span className="font-medium">Renderizar os cortes ao terminar</span>
            <span className="block text-xs text-muted-foreground">
              Os MP4 finais saem sozinhos depois da análise — bom para deixar rodando à noite. Dá para editar e renderizar de novo depois.
            </span>
          </span>
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={submit} disabled={invalid || analyze.isPending}>
            {analyze.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {paid && cost?.usd != null ? `Analisar · ≈ ${formatUsd(cost.usd)}` : 'Analisar'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
