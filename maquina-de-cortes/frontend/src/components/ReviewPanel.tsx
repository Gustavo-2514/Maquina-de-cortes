import { CircleDollarSign, Loader2, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { NativeSelect } from '@/components/ui/input'
import { parseReview, reviewIsCurrent, useClipActions, useClipReviewEstimate, useReviewEstimate } from '@/api/clips'
import { useAiModels, useUserSettings } from '@/api/system'
import type { Clip, Job, ReviewVerdict } from '@/api/types'
import { formatTime } from '@/lib/clip'
import { formatTokens, formatUsd } from '@/lib/format'

const VERDICT: Record<ReviewVerdict, { label: string; variant: 'success' | 'warning' | 'destructive' }> = {
  ok: { label: 'Revisado: pode postar', variant: 'success' },
  warn: { label: 'Revisado: vale ajustar', variant: 'warning' },
  bad: { label: 'Revisado: corrigir', variant: 'destructive' },
}

/** Selo da revisão visual (só quando vale para o MP4 atual). */
export function ReviewBadge({ c }: { c: Clip }) {
  const r = parseReview(c)
  if (!r.verdict || !reviewIsCurrent(c, r)) return null
  const v = VERDICT[r.verdict]
  return (
    <Badge variant={v.variant} title={r.summary}>
      <ShieldCheck className="size-3" /> {v.label}
    </Badge>
  )
}

/** Resultado da revisão + estado do job (abaixo do status de render). */
export function ReviewDetails({ c, job, error }: { c: Clip; job?: Job; error?: string }) {
  const r = parseReview(c)
  if (job)
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" /> {job.message || 'Revisão na fila…'}
      </p>
    )
  if (error) return <p className="mt-2 text-xs text-destructive">Revisão falhou: {error}</p>
  if (!r.verdict) return null
  const current = reviewIsCurrent(c, r)
  return (
    <div className="mt-2 space-y-1.5 rounded-lg border p-2.5 text-xs">
      <p className="font-medium">{r.summary}</p>
      {!!r.issues?.length && (
        <ul className="space-y-1">
          {r.issues.map((it, i) => (
            <li key={i} className="flex gap-2">
              <span className="shrink-0 tabular-nums text-muted-foreground" title="Segundo do corte">
                {formatTime(it.t)}
              </span>
              <span className={it.severity === 'grave' ? 'text-destructive' : 'text-muted-foreground'}>
                <b className="font-medium">{it.kind}</b> — {it.text}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-muted-foreground">
        {r.cost?.provider === 'claude-code'
          ? `${r.model} · sem custo em US$ (uso do plano${r.cost.tokens_approx ? ` ≈ ${formatTokens(r.cost.tokens_approx)} tokens` : ''})`
          : r.cost?.priced === false
            ? `${r.model} · ${r.cost.input_tokens + r.cost.output_tokens} tokens (preço não configurado)`
            : `${r.model} · custou ${formatUsd(r.cost?.usd)}`}
        {!current && ' · feita num render anterior — revise de novo para o MP4 atual'}
      </p>
    </div>
  )
}

/** Confirmação com custo estimado antes de revisar (um corte ou todos os renderizados). */
export function ReviewDialog({ projectId, clip, onClose }: { projectId: number; clip?: Clip; onClose: () => void }) {
  const { data: settings } = useUserSettings()
  const { data: models, isError: modelsError } = useAiModels()
  const [model, setModel] = useState<string | null>(null)
  const m = model ?? settings?.review_model ?? models?.default_review ?? 'claude-opus-5-5'
  const visionModels = models?.models.filter((x) => x.vision) ?? []
  const current = visionModels.find((x) => x.ref === m)
  const onlyClaude = !!models && visionModels.every((x) => x.provider === 'anthropic')
  const one = useClipReviewEstimate(clip?.id ?? 0, m, !!clip)
  const all = useReviewEstimate(projectId, m, !clip)
  const est = clip ? one.data : all.data
  const estError = (clip ? one.error : all.error) as Error | null
  const count = clip ? 1 : (all.data?.clips ?? 0)
  const { review, reviewAll } = useClipActions(projectId)
  const busy = review.isPending || reviewAll.isPending
  const noKey = est?.configured === false
  const onError = (e: Error) => toast.error(e.message)

  const go = () => {
    if (clip) review.mutate({ id: clip.id, model: m }, { onSuccess: () => (toast.success('Revisão na fila'), onClose()), onError })
    else reviewAll.mutate(m, { onSuccess: (js) => (toast.success(`${js.length} revisão(ões) na fila`), onClose()), onError })
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Revisão visual com IA"
      description={clip ? clip.title || 'Corte' : 'Cortes renderizados ainda sem revisão para o MP4 atual'}
      className="max-w-lg"
    >
      <div className="space-y-4 text-sm">
        <p className="text-muted-foreground">
          A IA olha 8 quadros do MP4 final e a fala do corte e aponta rosto cortado, legenda tapando algo, gancho fraco ou final no meio
          da frase. <b>É pago</b>: usa a sua chave do {current?.provider_label ?? 'provedor escolhido'}.
        </p>
        <label className="block space-y-1.5">
          <span className="font-medium">Modelo</span>
          <NativeSelect value={m} onChange={(e) => setModel(e.target.value)}>
            {!current && <option value={m}>{m}</option>}
            {visionModels.map((x) => (
              <option key={x.ref} value={x.ref} disabled={!x.configured}>
                {x.label}
                {!x.configured && ' (sem chave)'}
              </option>
            ))}
          </NativeSelect>
        </label>
        {onlyClaude && (
          <p className="text-xs text-muted-foreground">
            Para usar GPT, Gemini ou qualquer modelo do OpenRouter, salve a chave e adicione o modelo em{' '}
            <Link to="/configuracoes" className="text-primary underline-offset-4 hover:underline" onClick={onClose}>
              Configurações → IA paga
            </Link>
            . Só aparecem aqui modelos que aceitam imagens.
          </p>
        )}
        {(modelsError || estError) && (
          <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
            Não consegui calcular o custo{estError?.message ? ` (${estError.message})` : ''}. Se você acabou de atualizar o app,
            feche e rode <code>python run.py</code> de novo. Sem a estimativa, a revisão fica bloqueada.
          </p>
        )}
        {est && (
          <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-xs">
            <div className="mb-1 flex items-center gap-1.5 text-sm font-medium">
              <CircleDollarSign className="size-4" /> Custo estimado: {est.usd == null ? 'sem preço configurado' : `≈ ${formatUsd(est.usd)}`}
              {!clip && count > 0 && <span className="font-normal text-muted-foreground">({count} corte(s))</span>}
            </div>
            <p className="text-muted-foreground">
              ~{formatTokens(est.input_tokens)} tokens de entrada (imagens + fala) · ~{formatTokens(est.output_tokens)} de saída.{' '}
              {est.usd == null ? 'Informe o preço do modelo em Configurações para ver o valor em US$.' : `Preços de ${est.prices_as_of || 'tabela'};`} o custo
              real aparece em cada corte ao terminar.
            </p>
          </div>
        )}
        {!clip && all.data && count === 0 && <p className="text-xs text-muted-foreground">Nada a revisar: renderize cortes ou todos já foram revisados.</p>}
        {noKey && <p className="text-xs text-destructive">Configure a chave do {current?.provider_label ?? 'provedor'} em Configurações para usar.</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={go} disabled={busy || !est || count === 0 || noKey}>
            {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            {est?.usd != null ? `Revisar · ≈ ${formatUsd(est.usd)}` : 'Revisar'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
