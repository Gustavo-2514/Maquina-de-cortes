import {
  AlertTriangle,
  Ban,
  Check,
  Copy,
  Download,
  ImageIcon,
  Loader2,
  RefreshCw,
  Save,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input, Progress, Textarea } from "@/components/ui/input";
import {
  coverUrl,
  hasPostTexts,
  parsePost,
  parseTags,
  PLATFORM_LABELS,
  platformText,
  tagsLine,
  useClipActions,
} from "@/api/clips";
import { useJobActions } from "@/api/jobs";
import type { Clip, Job, Platform, PostPack } from "@/api/types";
import { formatTime } from "@/lib/clip";
import { cn } from "@/lib/utils";

const LIMITS = { tiktok: 300, reels: 600, shortsTitle: 100 };
const PLATFORMS: Platform[] = ["tiktok", "reels", "shorts"];

type Draft = {
  tiktok: { caption: string; tags: string };
  reels: { caption: string; tags: string };
  shorts: { title: string; description: string; tags: string };
};

function toDraft(p: PostPack): Draft {
  return {
    tiktok: {
      caption: p.tiktok?.caption ?? "",
      tags: tagsLine(p.tiktok?.hashtags ?? []),
    },
    reels: {
      caption: p.reels?.caption ?? "",
      tags: tagsLine(p.reels?.hashtags ?? []),
    },
    shorts: {
      title: p.shorts?.title ?? "",
      description: p.shorts?.description ?? "",
      tags: tagsLine(p.shorts?.hashtags ?? []),
    },
  };
}

function fromDraft(d: Draft): Required<Pick<PostPack, Platform>> {
  return {
    tiktok: { caption: d.tiktok.caption, hashtags: parseTags(d.tiktok.tags) },
    reels: { caption: d.reels.caption, hashtags: parseTags(d.reels.tags) },
    shorts: {
      title: d.shorts.title,
      description: d.shorts.description,
      hashtags: parseTags(d.shorts.tags),
    },
  };
}

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copiado`);
  } catch {
    toast.error("Não foi possível copiar — selecione o texto e use Ctrl+C");
  }
}

function Counter({ n, max }: { n: number; max: number }) {
  return (
    <span
      className={cn(
        "tabular-nums",
        n > max ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {n}/{max}
    </span>
  );
}

function Cover({
  c,
  titled,
  hasCover,
}: {
  c: Clip;
  titled: boolean;
  hasCover: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const src = coverUrl(c, titled);
  useEffect(() => setFailed(false), [src]);
  return (
    <figure className="space-y-1">
      <div className="relative aspect-[9/16] w-24 overflow-hidden rounded-md border bg-black">
        {hasCover && !failed ? (
          <img
            src={src}
            alt={titled ? "Capa com título" : "Capa"}
            className="size-full object-cover"
            onError={() => setFailed(true)}
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground">
            <ImageIcon className="size-5" />
          </div>
        )}
      </div>
      <figcaption className="flex w-24 items-center justify-between text-[11px] text-muted-foreground">
        {titled ? "Com título" : "Limpa"}
        {hasCover && !failed && (
          <a
            href={coverUrl(c, titled, true)}
            download
            className="hover:text-foreground"
            aria-label="Baixar capa"
          >
            <Download className="size-3.5" />
          </a>
        )}
      </figcaption>
    </figure>
  );
}

export function PostPackPanel({
  c,
  job,
  lastError,
}: {
  c: Clip;
  job: Job | undefined;
  lastError: string;
}) {
  const post = useMemo(() => parsePost(c), [c]);
  const { postPack, savePost } = useClipActions(c.project_id);
  const { cancel } = useJobActions();
  const [tab, setTab] = useState<Platform>("tiktok");
  const saved = useMemo(() => toDraft(post), [post]);
  const [draft, setDraft] = useState<Draft>(saved);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) setDraft(saved); // textos novos da IA entram se o usuário não estiver editando
  }, [saved, dirty]);

  const texts = hasPostTexts(post);
  const hasCover = !!post.cover_at;
  const busy = !!job || postPack.isPending;
  const onError = (e: Error) => toast.error(e.message);
  const generate = (t: boolean, cv: boolean) => {
    if (
      t &&
      dirty &&
      !window.confirm("Descartar suas edições e gerar textos novos?")
    )
      return;
    if (t) setDirty(false);
    postPack.mutate({ id: c.id, texts: t, cover: cv }, { onError });
  };
  const set = <K extends Platform>(k: K, patch: Partial<Draft[K]>) => {
    setDraft((d) => ({ ...d, [k]: { ...d[k], ...patch } }));
    setDirty(true);
  };
  const save = () =>
    savePost.mutate(
      { id: c.id, ...fromDraft(draft) },
      {
        onSuccess: () => (setDirty(false), toast.success("Textos salvos")),
        onError,
      },
    );
  const current = dirty ? { ...post, ...fromDraft(draft) } : post;

  return (
    <div className="mt-2 rounded-lg border bg-muted/30 p-3">
      {job ? (
        <div className="mb-3 flex items-center gap-3 text-xs">
          <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
          <div className="min-w-0 flex-1">
            <div className="text-muted-foreground">
              {job.status === "queued"
                ? "Na fila (espera a GPU ficar livre)…"
                : job.message}
            </div>
            {job.status === "running" && (
              <Progress value={job.progress} className="mt-1" />
            )}
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="h-7"
            onClick={() => cancel.mutate(job.id)}
          >
            <Ban /> Cancelar
          </Button>
        </div>
      ) : (
        lastError && (
          <div className="mb-3 flex items-start gap-2 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {lastError}
          </div>
        )
      )}

      {!texts && !hasCover ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-muted-foreground">
            A IA escreve legenda e hashtags para TikTok, Reels e Shorts a partir
            da fala do corte e escolhe o quadro mais nítido com rosto para a
            capa. Tudo local.
          </p>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => generate(true, true)}
          >
            {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Gerar
            textos e capa
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="shrink-0 space-y-2">
            <div className="flex gap-2">
              <Cover c={c} titled={false} hasCover={hasCover} />
              <Cover c={c} titled hasCover={hasCover && !!post.cover_title} />
            </div>
            {hasCover && post.cover_t != null && (
              <div className="text-[11px] text-muted-foreground">
                Quadro em {formatTime(post.cover_t)} do corte
              </div>
            )}
            <Button
              size="sm"
              variant="outline"
              className="h-7 w-full"
              disabled={busy}
              onClick={() => generate(false, true)}
            >
              <RefreshCw /> {hasCover ? "Escolher de novo" : "Gerar capa"}
            </Button>
          </div>

          <div className="min-w-0 flex-1 space-y-2.5">
            <div className="flex flex-wrap items-center gap-1">
              {PLATFORMS.map((k) => (
                <Button
                  key={k}
                  size="sm"
                  variant={tab === k ? "secondary" : "ghost"}
                  className="h-7"
                  onClick={() => setTab(k)}
                >
                  {PLATFORM_LABELS[k]}
                </Button>
              ))}
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto h-7"
                disabled={busy}
                onClick={() => generate(true, false)}
              >
                <Sparkles /> {texts ? "Reescrever" : "Gerar textos"}
              </Button>
            </div>

            {!texts && !dirty ? (
              <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
                Textos ainda não gerados.
              </p>
            ) : tab === "shorts" ? (
              <>
                <label className="block space-y-1">
                  <span className="flex justify-between text-xs font-medium">
                    Título{" "}
                    <Counter
                      n={draft.shorts.title.length}
                      max={LIMITS.shortsTitle}
                    />
                  </span>
                  <div className="flex gap-1">
                    <Input
                      value={draft.shorts.title}
                      onChange={(e) => set("shorts", { title: e.target.value })}
                    />
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-9 shrink-0"
                      aria-label="Copiar título"
                      onClick={() => copy(draft.shorts.title, "Título")}
                    >
                      <Copy />
                    </Button>
                  </div>
                </label>
                <label className="block space-y-1">
                  <span className="text-xs font-medium">Descrição</span>
                  <Textarea
                    rows={3}
                    value={draft.shorts.description}
                    onChange={(e) =>
                      set("shorts", { description: e.target.value })
                    }
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-xs font-medium">
                    Hashtags{" "}
                    <span className="font-normal text-muted-foreground">
                      (#Shorts entra sozinha)
                    </span>
                  </span>
                  <Input
                    value={draft.shorts.tags}
                    onChange={(e) => set("shorts", { tags: e.target.value })}
                  />
                </label>
              </>
            ) : (
              <>
                <label className="block space-y-1">
                  <span className="flex justify-between text-xs font-medium">
                    Legenda{" "}
                    <Counter n={draft[tab].caption.length} max={LIMITS[tab]} />
                  </span>
                  <Textarea
                    rows={tab === "reels" ? 4 : 2}
                    value={draft[tab].caption}
                    onChange={(e) => set(tab, { caption: e.target.value })}
                  />
                </label>
                <label className="block space-y-1">
                  <span className="text-xs font-medium">Hashtags</span>
                  <Input
                    value={draft[tab].tags}
                    onChange={(e) => set(tab, { tags: e.target.value })}
                  />
                </label>
              </>
            )}

            {(texts || dirty) && (
              <div className="flex flex-wrap items-center justify-end gap-2">
                {dirty && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7"
                    onClick={() => (setDraft(saved), setDirty(false))}
                  >
                    Desfazer
                  </Button>
                )}
                {dirty && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
                    disabled={savePost.isPending}
                    onClick={save}
                  >
                    <Save /> Salvar
                  </Button>
                )}
                <Button
                  size="sm"
                  className="h-7"
                  onClick={() =>
                    copy(
                      platformText(current, tab),
                      `Texto do ${PLATFORM_LABELS[tab]}`,
                    )
                  }
                >
                  <Copy /> Copiar para o {PLATFORM_LABELS[tab]}
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function PostPackBadge({ c }: { c: Clip }) {
  const p = parsePost(c);
  if (!hasPostTexts(p) && !p.cover_at) return null;
  return (
    <span
      className="inline-flex items-center gap-0.5 text-[11px] text-success"
      title="Textos/capa prontos"
    >
      <Check className="size-3" /> pacote
    </span>
  );
}
