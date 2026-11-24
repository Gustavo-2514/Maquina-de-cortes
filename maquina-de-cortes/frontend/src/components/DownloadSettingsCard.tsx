import { Download, Loader2, Save } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useSaveSettings, useUpdateYtdlp, useUserSettings, useYtdlpVersion } from '@/api/system'

export function DownloadSettingsCard() {
  const { data: version } = useYtdlpVersion()
  const update = useUpdateYtdlp()
  const { data: settings } = useUserSettings()
  const save = useSaveSettings()
  const [draft, setCookies] = useState<string | null>(null) // null = sem edição local
  const cookies = draft ?? settings?.cookies_path ?? ''

  const doUpdate = () =>
    update.mutate(undefined, {
      onSuccess: (r) => toast.success(`yt-dlp ${r.version} instalado. Reinicie o app para o download usar a nova versão.`),
      onError: (e) => toast.error(e.message),
    })

  const saveCookies = () => {
    if (!settings) return
    save.mutate(
      { ...settings, cookies_path: cookies.trim() },
      { onSuccess: () => (setCookies(null), toast.success('Configuração salva')), onError: (e) => toast.error(e.message) },
    )
  }

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Download className="size-4" /> Downloads
        </CardTitle>
        <CardDescription>Os sites mudam com frequência; se um download falhar, atualize o yt-dlp.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm">
            yt-dlp <span className="font-mono text-muted-foreground">{version?.version ?? '…'}</span>
          </div>
          <Button size="sm" variant="outline" onClick={doUpdate} disabled={update.isPending}>
            {update.isPending && <Loader2 className="animate-spin" />}
            {update.isPending ? 'Atualizando…' : 'Atualizar yt-dlp'}
          </Button>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="cookies" className="text-sm font-medium">
            Arquivo cookies.txt (opcional)
          </label>
          <div className="flex gap-2">
            <Input
              id="cookies"
              value={cookies}
              onChange={(e) => setCookies(e.target.value)}
              placeholder="/home/voce/cookies.txt"
              className="font-mono text-xs"
            />
            <Button size="icon" variant="outline" onClick={saveCookies} disabled={save.isPending || cookies === settings?.cookies_path} aria-label="Salvar">
              <Save />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Para vídeos que pedem login ou idade. Exporte no formato Netscape com uma extensão como "Get cookies.txt LOCALLY".
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
