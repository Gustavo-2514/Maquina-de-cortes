import { Film } from 'lucide-react'
import { useState } from 'react'
import { useDownloads } from '@/api/downloads'
import { mediaUrl } from '@/api/projects'
import type { Project } from '@/api/types'

export function ProjectThumb({ p }: { p: Project }) {
  const [attempt, setAttempt] = useState(0)
  const { data: downloads } = useDownloads()
  const dlThumb = downloads?.find((d) => d.id === p.download_id)?.thumbnail_url
  // miniaturas geradas no projeto (~10 s, depois 0 s) → thumb do download → ícone
  const sources = [mediaUrl(p.id, 'thumbs/00002.jpg'), mediaUrl(p.id, 'thumbs/00001.jpg'), dlThumb].filter(Boolean) as string[]
  const src = sources[attempt]
  return src ? (
    <img
      key={src}
      src={src}
      alt=""
      width={640}
      height={360}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setAttempt((a) => a + 1)}
      className="aspect-video h-auto w-full bg-muted object-cover"
    />
  ) : (
    <div className="grid aspect-video w-full place-items-center bg-muted text-muted-foreground">
      <Film className="size-8" />
    </div>
  )
}
