import { ExternalLink, Eye, Loader2, Plus, RefreshCw, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox, Input, NativeSelect } from '@/components/ui/input'
import {
  type AiModelEntry,
  type AiProvider,
  type UserSettings,
  testAiKey,
  testClaude,
  useAiCatalog,
  useAiModels,
  useAiProviders,
  useClaudeModels,
} from '@/api/system'
import { formatUsd } from '@/lib/format'

type SetFn = <K extends keyof UserSettings>(k: K, v: UserSettings[K]) => void

function Field({ label, hint, children }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  )
}

const refOf = (provider: string, id: string, claudeIds: string[]) =>
  provider === 'anthropic' && claudeIds.includes(id) ? id : `${provider}:${id}`

const price = (v: number | null) => (v == null ? '?' : v < 0.01 && v > 0 ? v.toFixed(4) : String(+v.toFixed(3)))

const numOrNull = (v: string) => (v.trim() === '' || Number.isNaN(Number(v.replace(',', '.'))) ? null : Number(v.replace(',', '.')))

/** Chaves por provedor + modelos adicionados + modelo padrão da revisão. Edita o rascunho do PreferencesCard. */
export function AiProvidersSection({ s, set, dirty }: { s: UserSettings; set: SetFn; dirty: boolean }) {
  const { data: providersData } = useAiProviders()
  const { data: claudeModels } = useClaudeModels()
  const { data: aiModels } = useAiModels()
  const providers = providersData?.providers ?? []
  const claudeIds = claudeModels?.models.map((m) => m.id) ?? ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5']
  const [extra, setExtra] = useState<string[]>([])
  const [testing, setTesting] = useState<string | null>(null)

  // provedores visíveis: Anthropic e OpenRouter sempre; os demais quando têm chave/modelo ou foram abertos agora
  const shown = providers.filter(
    (p) => p.key === 'anthropic' || p.key === 'openrouter' || p.configured || !!s.api_keys[p.key] || extra.includes(p.key) || s.ai_models.some((m) => m.provider === p.key),
  )
  const hidden = providers.filter((p) => !shown.includes(p))

  const setKey = (provider: string, v: string) => set('api_keys', { ...s.api_keys, [provider]: v })

  const runTest = async (p: AiProvider) => {
    setTesting(p.key)
    try {
      if (p.key === 'anthropic') {
        // o teste do Claude faz um pedido mínimo ao Haiku (fração de centavo)
        const r = await testClaude(s.anthropic_api_key, 'claude-haiku-5-5')
        if (r.ok) toast.success(`${r.message} O teste custou ${formatUsd(r.cost?.usd)}.`)
        else toast.error(r.message, { description: r.detail })
      } else {
        const r = await testAiKey(p.key, s.api_keys[p.key] ?? '', p.key === 'custom' ? s.custom_base_url : '')
        if (r.ok) toast.success(`${r.message} Sem custo.`)
        else toast.error(r.message, { description: r.detail })
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Falhou')
    } finally {
      setTesting(null)
    }
  }

  // modelo padrão da revisão: só os com visão; inclui os do rascunho ainda não salvos
  const reviewOptions = (() => {
    const saved = (aiModels?.models ?? []).filter((m) => m.vision).map((m) => ({ ref: m.ref, label: m.label }))
    const draft = s.ai_models
      .filter((m) => m.vision)
      .map((m) => ({ ref: refOf(m.provider, m.id, claudeIds), label: `${m.label || m.id} · ${providers.find((p) => p.key === m.provider)?.label ?? m.provider}` }))
    const all = [...(saved.length ? saved : claudeIds.map((id) => ({ ref: id, label: id })))]
    for (const d of draft) if (!all.some((a) => a.ref === d.ref)) all.push(d)
    return all
  })()

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">IA paga por chave de API (opcional)</h3>
        <p className="text-xs text-muted-foreground">
          Alternativa à IA local na análise e na revisão visual dos cortes. Use a chave do provedor que você já paga — Claude, OpenRouter (centenas de
          modelos com uma chave só), OpenAI, Gemini e outros. O custo estimado aparece antes de cada ação e o custo real depois. As chaves ficam só neste
          computador (data/settings.json); sem chave, nada é enviado.
        </p>
      </div>

      <div className="space-y-3">
        {shown.map((p) => {
          const isClaude = p.key === 'anthropic'
          const value = isClaude ? s.anthropic_api_key : (s.api_keys[p.key] ?? '')
          return (
            <div key={p.key} className="space-y-2">
              <Field
                label={
                  <span className="flex items-center gap-2">
                    {p.label}
                    {p.configured && <Badge variant="success">com chave</Badge>}
                    {p.keys_url && (
                      <a href={p.keys_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-xs font-normal text-muted-foreground hover:text-foreground">
                        pegar chave <ExternalLink className="size-3" />
                      </a>
                    )}
                  </span>
                }
                hint={`Vazio = usa ${p.env} do ambiente.`}
              >
                <div className="flex gap-2">
                  <Input
                    type="password"
                    autoComplete="off"
                    value={value}
                    onChange={(e) => (isClaude ? set('anthropic_api_key', e.target.value) : setKey(p.key, e.target.value))}
                    placeholder={p.key_hint || 'chave da API'}
                    className="font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    onClick={() => runTest(p)}
                    disabled={testing === p.key || dirty}
                    title={dirty ? 'Salve antes de testar' : isClaude ? 'Pedido mínimo ao Claude Haiku (fração de centavo)' : 'Valida a chave sem gastar nada'}
                  >
                    {testing === p.key ? <Loader2 className="animate-spin" /> : <Zap />} Testar
                  </Button>
                </div>
              </Field>
              {p.key === 'custom' && (
                <Field label="Endereço da API (base URL)" hint="Qualquer servidor compatível com a API da OpenAI, terminando em /v1.">
                  <Input
                    value={s.custom_base_url}
                    onChange={(e) => set('custom_base_url', e.target.value)}
                    placeholder="https://api.together.xyz/v1"
                    className="font-mono text-xs"
                  />
                </Field>
              )}
            </div>
          )
        })}
        {hidden.length > 0 && (
          <NativeSelect
            value=""
            onChange={(e) => e.target.value && setExtra((x) => [...x, e.target.value])}
            className="w-auto text-muted-foreground"
            aria-label="Adicionar chave de outro provedor"
          >
            <option value="">+ Adicionar chave de outro provedor…</option>
            {hidden.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </NativeSelect>
        )}
      </div>

      <ModelList s={s} set={set} dirty={dirty} providers={providers} />

      <Field label="Modelo padrão da revisão visual" hint="Só aparecem modelos que aceitam imagens.">
        <NativeSelect value={s.review_model} onChange={(e) => set('review_model', e.target.value)}>
          {!reviewOptions.some((o) => o.ref === s.review_model) && <option value={s.review_model}>{s.review_model} (removido)</option>}
          {reviewOptions.map((o) => (
            <option key={o.ref} value={o.ref}>
              {o.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
    </section>
  )
}

function ModelList({ s, set, dirty, providers }: { s: UserSettings; set: SetFn; dirty: boolean; providers: AiProvider[] }) {
  const addable = providers.filter((p) => p.key !== 'anthropic')
  const labelOf = (k: string) => providers.find((p) => p.key === k)?.label ?? k
  const remove = (i: number) => set('ai_models', s.ai_models.filter((_, j) => j !== i))

  return (
    <div className="space-y-2">
      <div>
        <span className="text-sm font-medium">Modelos de outros provedores</span>
        <p className="text-xs text-muted-foreground">
          Os do Claude já vêm prontos. Adicione aqui os que quiser usar dos outros provedores — eles aparecem na análise e na revisão.
        </p>
      </div>
      {s.ai_models.length > 0 && (
        <ul className="divide-y rounded-md border text-xs">
          {s.ai_models.map((m, i) => (
            <li key={`${m.provider}:${m.id}`} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{m.label || m.id}</div>
                <div className="truncate font-mono text-muted-foreground">
                  {labelOf(m.provider)} · {m.id}
                </div>
              </div>
              {m.vision && (
                <span title="Aceita imagens (serve para a revisão visual)">
                  <Eye className="size-3.5 text-muted-foreground" />
                </span>
              )}
              <span className="shrink-0 tabular-nums text-muted-foreground" title="US$ por milhão de tokens (entrada / saída)">
                {m.input_per_mtok == null || m.output_per_mtok == null ? 'sem preço' : `US$ ${price(m.input_per_mtok)} / ${price(m.output_per_mtok)}`}
              </span>
              <Button variant="ghost" size="icon" onClick={() => remove(i)} title="Remover" className="size-7">
                <Trash2 className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {addable.length > 0 && <AddModel s={s} set={set} dirty={dirty} providers={addable} />}
    </div>
  )
}

const EMPTY = { id: '', label: '', input: '', output: '', vision: true, prices_as_of: '' }

function AddModel({ s, set, dirty, providers }: { s: UserSettings; set: SetFn; dirty: boolean; providers: AiProvider[] }) {
  const [provider, setProvider] = useState(providers[0]?.key ?? 'openrouter')
  const [form, setForm] = useState(EMPTY)
  const [loadCatalog, setLoadCatalog] = useState(false)
  const p = providers.find((x) => x.key === provider)
  // OpenRouter: catálogo público com preços (carrega sozinho). Outros: GET /models com a chave salva, sob demanda.
  const catalogOn = provider === 'openrouter' || loadCatalog
  const catalog = useAiCatalog(provider, catalogOn)
  const listId = `ai-catalog-${provider}`

  const pick = (id: string) => {
    const c = catalog.data?.models.find((m) => m.id === id)
    if (!c) return setForm((f) => ({ ...f, id }))
    setForm({
      id: c.id,
      label: c.label,
      input: c.input_per_mtok == null ? '' : String(c.input_per_mtok),
      output: c.output_per_mtok == null ? '' : String(c.output_per_mtok),
      vision: c.vision,
      prices_as_of: c.prices_as_of,
    })
  }

  const add = () => {
    const id = form.id.trim()
    if (!id) return
    if (s.ai_models.some((m) => m.provider === provider && m.id === id)) return toast.error('Esse modelo já está na lista')
    const entry: AiModelEntry = {
      provider,
      id,
      label: form.label.trim(),
      input_per_mtok: numOrNull(form.input),
      output_per_mtok: numOrNull(form.output),
      vision: form.vision,
      prices_as_of: form.prices_as_of || (numOrNull(form.input) != null ? new Date().toISOString().slice(0, 10) : ''),
    }
    set('ai_models', [...s.ai_models, entry])
    setForm({ ...EMPTY, vision: p?.vision_default ?? true })
    toast.message('Modelo adicionado — salve as preferências para usar')
  }

  return (
    <div className="space-y-3 rounded-md border border-dashed p-3">
      <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
        <Field label="Provedor">
          <NativeSelect
            value={provider}
            onChange={(e) => {
              const k = e.target.value
              setProvider(k)
              setLoadCatalog(false)
              setForm({ ...EMPTY, vision: providers.find((x) => x.key === k)?.vision_default ?? true })
            }}
          >
            {providers.map((x) => (
              <option key={x.key} value={x.key}>
                {x.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field
          label="ID do modelo"
          hint={
            catalog.isFetching
              ? 'Buscando modelos…'
              : catalog.error
                ? catalog.error.message
                : catalog.data
                  ? `${catalog.data.models.length} modelos — digite para filtrar.${provider === 'openrouter' ? ' Preços vêm do OpenRouter.' : ' Preços: informe os da página do provedor.'}`
                  : provider === 'openrouter'
                    ? undefined
                    : 'Digite o ID ou busque a lista do provedor (usa a chave salva, sem custo).'
          }
        >
          <div className="flex gap-2">
            <Input
              list={listId}
              value={form.id}
              onChange={(e) => pick(e.target.value)}
              placeholder={provider === 'openrouter' ? 'ex.: anthropic/…, openai/…, google/…' : 'ID exato do modelo'}
              className="font-mono text-xs"
            />
            {provider !== 'openrouter' && (
              <Button
                variant="outline"
                onClick={() => (loadCatalog ? catalog.refetch() : setLoadCatalog(true))}
                disabled={catalog.isFetching || dirty}
                title={dirty ? 'Salve a chave antes de buscar' : 'Lista os modelos da sua conta'}
              >
                {catalog.isFetching ? <Loader2 className="animate-spin" /> : <RefreshCw />} Buscar
              </Button>
            )}
          </div>
          <datalist id={listId}>
            {catalog.data?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
                {m.input_per_mtok != null && m.output_per_mtok != null ? ` · US$ ${price(m.input_per_mtok)} / ${price(m.output_per_mtok)}` : ''}
              </option>
            ))}
          </datalist>
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_7rem_7rem]">
        <Field label="Nome (opcional)">
          <Input value={form.label} onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))} placeholder={form.id || 'Como aparece na lista'} />
        </Field>
        <Field label="US$/M entrada">
          <Input inputMode="decimal" value={form.input} onChange={(e) => setForm((f) => ({ ...f, input: e.target.value }))} placeholder="?" className="tabular-nums" />
        </Field>
        <Field label="US$/M saída">
          <Input inputMode="decimal" value={form.output} onChange={(e) => setForm((f) => ({ ...f, output: e.target.value }))} placeholder="?" className="tabular-nums" />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={form.vision} onChange={(e) => setForm((f) => ({ ...f, vision: e.target.checked }))} />
          Aceita imagens (para a revisão visual)
        </label>
        <Button variant="secondary" onClick={add} disabled={!form.id.trim()}>
          <Plus /> Adicionar modelo
        </Button>
      </div>
      {(numOrNull(form.input) == null || numOrNull(form.output) == null) && form.id.trim() && (
        <p className="text-xs text-warning">Sem preço, o app não consegue estimar nem somar o custo em US$ — só os tokens.</p>
      )}
    </div>
  )
}
