import { Loader2, Scissors } from 'lucide-react'
import { useState } from 'react'
import { useTemplates } from '@/api/clips'
import { TemplatePicker } from '@/components/TemplatePicker'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/input'
import { loadStartPrefs, prefsFromTemplate, saveStartPrefs, type StartPrefs } from '@/lib/startPrefs'

/** Antes de baixar: tipo de conteúdo (template) e se já renderiza ao final — o pipeline roda sozinho até o MP4. */
export function CreateClipsDialog({
  title,
  busy,
  onClose,
  onConfirm,
}: {
  title: string
  busy: boolean
  onClose: () => void
  onConfirm: (prefs: StartPrefs) => void
}) {
  const [prefs, setPrefs] = useState(loadStartPrefs)
  const { data: templates } = useTemplates()
  const confirm = () => {
    // reconfere o template salvo com a lista atual (enquadramento/legenda podem ter mudado)
    const t = templates?.find((x) => x.key === prefs.template)
    const final = t ? prefsFromTemplate(t, prefs.auto_render) : prefs
    saveStartPrefs(final)
    onConfirm(final)
  }
  return (
    <Dialog open onClose={onClose} title="Criar cortes" description={title} className="max-w-xl">
      <div className="space-y-4">
        <div className="text-xs font-medium text-muted-foreground">Que tipo de vídeo é este?</div>
        <TemplatePicker value={prefs.template} onChange={(t) => setPrefs((p) => prefsFromTemplate(t, p.auto_render))} />
        <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2.5">
          <Checkbox checked={prefs.auto_render} onChange={(e) => setPrefs((p) => ({ ...p, auto_render: e.target.checked }))} className="mt-0.5" />
          <span className="text-sm">
            <span className="font-medium">Já renderizar os cortes</span>
            <span className="block text-xs text-muted-foreground">
              Baixa, transcreve, escolhe os trechos e gera os MP4 finais sozinho — bom para deixar rodando à noite.
            </span>
          </span>
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button onClick={confirm} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Scissors />} Criar cortes
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
