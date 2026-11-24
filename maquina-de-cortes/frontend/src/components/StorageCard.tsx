import { HardDrive, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox, NativeSelect } from '@/components/ui/input'
import { useCleanup, useStorage } from '@/api/system'
import { formatBytes } from '@/lib/format'

const FOLDERS: [keyof NonNullable<ReturnType<typeof useStorage>['data']>['folders'], string][] = [
  ['downloads', 'Downloads'],
  ['projects', 'Projetos (proxies, áudio, análises)'],
  ['exports', 'Cortes exportados'],
  ['logs', 'Logs'],
]

const size = (n: number) => (n ? formatBytes(n) : '0 B')

export function StorageCard() {
  const [days, setDays] = useState(30)
  const { data, isFetching } = useStorage(days)
  const cleanup = useCleanup()
  const [sel, setSel] = useState({ temp: true, audio: false, proxies: false })

  const total = data ? Object.values(data.folders).reduce((a, b) => a + b, 0) : 0
  const selectedBytes = data ? (Object.keys(sel) as (keyof typeof sel)[]).reduce((a, k) => a + (sel[k] ? data.cleanable[k].bytes : 0), 0) : 0

  const options: { k: keyof typeof sel; label: string; hint: string }[] = [
    { k: 'temp', label: 'Temporários e restos', hint: 'Downloads interrompidos, renders pela metade, pastas de projetos/cortes apagados. Sempre seguro.' },
    { k: 'audio', label: 'Áudio da transcrição (audio.wav)', hint: 'Só de projetos prontos. É recriado se você reanalisar.' },
    { k: 'proxies', label: 'Vídeo de edição (proxy) de projetos parados', hint: 'O editor pede para “Preparar de novo” (rápido) quando você voltar a eles.' },
  ]

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HardDrive className="size-4" /> Armazenamento
          {isFetching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        </CardTitle>
        <CardDescription className="truncate" title={data?.data_dir}>
          {data ? `${formatBytes(data.free_bytes)} livres de ${formatBytes(data.total_bytes)} · app usa ${formatBytes(total)}` : 'Calculando…'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data && (
          <dl className="space-y-1.5 text-sm">
            {FOLDERS.map(([k, label]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="whitespace-nowrap tabular-nums">{size(data.folders[k])}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="space-y-2 border-t pt-4">
          <div className="text-sm font-medium">Limpar arquivos temporários</div>
          {options.map((o) => (
            <label key={o.k} className="flex cursor-pointer gap-2 text-sm">
              <Checkbox className="mt-0.5" checked={sel[o.k]} onChange={(e) => setSel({ ...sel, [o.k]: e.target.checked })} />
              <span className="min-w-0 flex-1">
                <span className="flex justify-between gap-2">
                  {o.label}
                  <span className="whitespace-nowrap text-muted-foreground tabular-nums">{data ? size(data.cleanable[o.k].bytes) : '…'}</span>
                </span>
                <span className="block text-xs text-muted-foreground">{o.hint}</span>
                {o.k === 'proxies' && (
                  <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    sem uso há mais de
                    <NativeSelect value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-7 w-24 py-0 text-xs">
                      {[7, 30, 90, 0].map((d) => (
                        <option key={d} value={d}>
                          {d === 0 ? 'qualquer' : `${d} dias`}
                        </option>
                      ))}
                    </NativeSelect>
                  </span>
                )}
              </span>
            </label>
          ))}
          <Button
            variant="outline"
            className="w-full"
            disabled={!selectedBytes || cleanup.isPending}
            onClick={() =>
              cleanup.mutate(
                { ...sel, proxy_days: days },
                {
                  onSuccess: (r) => toast.success(`${formatBytes(r.freed_bytes)} liberados (${r.removed} item(ns))`),
                  onError: (e) => toast.error(e.message),
                },
              )
            }
          >
            {cleanup.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />} {selectedBytes ? `Liberar ${size(selectedBytes)}` : 'Nada para liberar'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
