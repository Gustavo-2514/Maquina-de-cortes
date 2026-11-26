import { CircleAlert, CircleCheck, CircleX, Cpu, RefreshCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { DownloadSettingsCard } from '@/components/DownloadSettingsCard'
import { PreferencesCard } from '@/components/PreferencesCard'
import { StorageCard } from '@/components/StorageCard'
import { PageHeader, LoadError } from '@/components/Layout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useSystemCheck, type CheckItem } from '@/api/system'
import { cn } from '@/lib/utils'

function StatusIcon({ item }: { item: CheckItem }) {
  if (item.ok) return <CircleCheck className="size-5 text-success" />
  if (item.optional) return <CircleAlert className="size-5 text-warning" />
  return <CircleX className="size-5 text-destructive" />
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, isFetching, error } = useSystemCheck()

  const recheck = () => qc.invalidateQueries({ queryKey: ['system', 'check'] })

  return (
    <>
      <PageHeader
        title="Configurações"
        description="Diagnóstico do sistema e preferências."
        actions={
          <Button variant="outline" onClick={recheck} disabled={isFetching}>
            <RefreshCw className={cn(isFetching && 'animate-spin')} />
            Verificar novamente
          </Button>
        }
      />
      <div className="grid gap-6 px-8 pb-8 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Diagnóstico
              {data && (data.ok ? <Badge variant="success">Tudo certo</Badge> : <Badge variant="destructive">Pendências</Badge>)}
            </CardTitle>
            <CardDescription>Itens marcados em vermelho são obrigatórios: sem eles, partes do app não funcionam. O ícone de alerta indica um item opcional.</CardDescription>
          </CardHeader>
          <CardContent>
            {error && <LoadError what="o diagnóstico" error={error} />}
            {!data && !error && <p className="text-sm text-muted-foreground">Verificando…</p>}
            <ul className="divide-y">
              {data?.items.map((item) => (
                <li key={item.key} className="flex gap-3 py-3">
                  <StatusIcon item={item} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      {item.label}
                      {item.optional && <span className="text-xs font-normal text-muted-foreground">(opcional)</span>}
                    </div>
                    <div className="truncate text-xs text-muted-foreground" title={item.detail}>
                      {item.detail}
                    </div>
                    {!item.ok && item.fix && (
                      <code className="mt-1.5 block rounded bg-muted px-2 py-1 text-xs break-all select-all">{item.fix}</code>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <PreferencesCard />
        </div>
        <div className="space-y-6">
        {data && (
          <Card className="h-fit">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Cpu className="size-4" /> Hardware
              </CardTitle>
              <CardDescription>Padrões escolhidos automaticamente.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">GPU</dt>
                <dd>{data.hardware.gpu_name ?? 'nenhuma'}</dd>
                <dt className="text-muted-foreground">VRAM</dt>
                <dd>{data.hardware.vram_mb ? `${(data.hardware.vram_mb / 1024).toFixed(0)} GB` : '—'}</dd>
                <dt className="text-muted-foreground">Whisper</dt>
                <dd>
                  {data.recommended.whisper.model} · {data.recommended.whisper.device} · {data.recommended.whisper.compute_type}
                </dd>
                <dt className="text-muted-foreground">LLM</dt>
                <dd>{data.recommended.ollama_model}</dd>
                <dt className="text-muted-foreground">Encoder</dt>
                <dd>{data.recommended.encoder}</dd>
              </dl>
            </CardContent>
          </Card>
        )}
        <StorageCard />
        <DownloadSettingsCard />
        </div>
      </div>
    </>
  )
}
