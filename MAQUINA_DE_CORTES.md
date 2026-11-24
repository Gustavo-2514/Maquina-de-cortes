# Máquina de Cortes Local — Especificação do Projeto

> **Para o Claude Code:** este documento é a especificação completa do projeto. Construa **fase por fase** (seção 12), na ordem. Ao fim de cada fase, rode o projeto, confira os critérios de aceite e só então avance. Se algo aqui estiver ambíguo, escolha a opção mais simples que funcione e anote a decisão em `DECISIONS.md`. Antes de começar, pergunte ao usuário: **sistema operacional** (Windows/Linux/macOS) e **se tem placa NVIDIA (modelo/VRAM)**. O código deve funcionar com e sem GPU.

---

## 1. Visão geral

Um app **100% local** (nada de API paga, nada de nuvem) que funciona como um "Opus Clip caseiro":

1. **Baixa** vídeos por link (YouTube, Twitch, TikTok, Instagram, X, etc.) — área dedicada de downloads.
2. **Transcreve** o vídeo com timestamp de cada palavra.
3. **Encontra os melhores trechos** com um LLM local e dá uma nota de "potencial viral".
4. **Gera cortes verticais 9:16** com reenquadramento automático no rosto de quem fala.
5. **Coloca legendas animadas** palavra por palavra.
6. **Permite editar** cada corte num editor (ajustar início/fim, legenda, estilo, enquadramento, título) antes de exportar.
7. **Exporta** MP4 pronto para Shorts/Reels/TikTok.

Roda no navegador em `http://localhost:8000`, iniciado com um único comando.

### Fora do escopo (por enquanto)
- Postagem automática nas redes.
- Multiusuário, login, deploy em servidor.
- Geração de vídeo/imagem por IA.

---

## 2. Stack (e por quê)

| Camada | Escolha | Motivo |
|---|---|---|
| Backend | **Python 3.11+ / FastAPI** | Todo o ecossistema de IA/vídeo (Whisper, OpenCV, MediaPipe, yt-dlp) é Python. |
| Banco | **SQLite + SQLModel** | Zero configuração, um arquivo só, ideal para app local. |
| Fila de jobs | **Worker próprio em processo separado** (lendo a tabela `jobs` do SQLite) | Evita Redis/Celery. Jobs de GPU rodam um por vez. |
| Progresso em tempo real | **Server-Sent Events (SSE)** | Mais simples que WebSocket para fluxo servidor → cliente. |
| Download | **yt-dlp** (API Python) | Suporta centenas de sites. |
| Transcrição | **faster-whisper** | Whisper local, rápido, com timestamps por palavra. |
| LLM | **Ollama** (HTTP local) | Fácil de instalar e trocar modelo. Saída em JSON estruturado. |
| Visão | **OpenCV + MediaPipe Face Detection** + **PySceneDetect** | Detecção de rosto leve e detecção de troca de cena. |
| Vídeo | **FFmpeg** (binário do sistema) | Corte, encode, legenda (filtro `ass`), mixagem. |
| Frontend | **React + Vite + TypeScript** | Editor interativo precisa de componentes ricos. |
| UI | **Tailwind CSS + shadcn/ui + lucide-react** | Visual moderno rápido. |
| Estado/dados | **TanStack Query** (servidor) + **Zustand** (editor) | Cache de API + estado local do editor. |
| Timeline/onda | **wavesurfer.js** (+ plugin Regions) | Forma de onda e arrastar início/fim do corte. |

Em produção, o FastAPI **serve o build do frontend** (`frontend/dist`) — o usuário abre só uma porta.

---

## 3. Pré-requisitos do sistema

- Python 3.11+
- Node.js 20+ (só para desenvolver/buildar o frontend)
- **FFmpeg** no PATH (com `libass` habilitado — builds oficiais do gyan.dev/BtbN no Windows já têm)
- **Ollama** instalado e rodando (`ollama serve`), com um modelo baixado:
  - Com GPU ≥ 8 GB: `qwen2.5:7b` ou `llama3.1:8b`
  - Sem GPU / pouca VRAM: `qwen2.5:3b` ou `llama3.2:3b`
- GPU NVIDIA opcional (CUDA + cuDNN para faster-whisper em GPU)

O app deve ter uma **tela de diagnóstico** (Configurações) que verifica cada item acima e mostra ✅/❌ com instrução de correção.

---

## 4. Estrutura de pastas

```
maquina-de-cortes/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, monta rotas e serve frontend/dist
│   │   ├── config.py            # Settings (pydantic-settings) + settings.json do usuário
│   │   ├── db.py                # engine SQLite, sessão
│   │   ├── models.py            # SQLModel: tabelas
│   │   ├── schemas.py           # DTOs de request/response
│   │   ├── events.py            # broker SSE (pub/sub em memória + polling do DB)
│   │   ├── api/
│   │   │   ├── downloads.py
│   │   │   ├── projects.py
│   │   │   ├── clips.py
│   │   │   ├── jobs.py
│   │   │   ├── media.py         # streaming de arquivos com HTTP Range
│   │   │   └── system.py        # diagnóstico, settings, presets
│   │   ├── services/
│   │   │   ├── downloader.py    # yt-dlp
│   │   │   ├── probe.py         # ffprobe
│   │   │   ├── proxy.py         # gera proxy 540p + waveform peaks + thumbnails
│   │   │   ├── transcriber.py   # faster-whisper
│   │   │   ├── highlighter.py   # Ollama + heurísticas
│   │   │   ├── reframer.py      # rosto/cena → trilha de crop
│   │   │   ├── captions.py      # gera .ass
│   │   │   ├── renderer.py      # monta comando ffmpeg final
│   │   │   └── hardware.py      # detecta CUDA, NVENC, VRAM
│   │   └── worker/
│   │       ├── runner.py        # loop do worker
│   │       └── tasks.py         # handlers por tipo de job
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Downloads, Projetos, Projeto, Editor, Fila, Configurações
│   │   ├── components/
│   │   ├── editor/              # player, timeline, transcrição, painel de estilo, overlay de legenda
│   │   ├── api/                 # cliente tipado + hooks TanStack Query
│   │   ├── stores/              # zustand
│   │   └── lib/
│   └── package.json
├── data/                        # (gitignored) tudo que o app gera
│   ├── app.db
│   ├── downloads/
│   ├── projects/<project_id>/
│   │   ├── source.mp4
│   │   ├── proxy.mp4
│   │   ├── audio.wav
│   │   ├── waveform.json
│   │   ├── transcript.json
│   │   ├── scenes.json
│   │   ├── faces.json
│   │   └── clips/<clip_id>/{captions.ass, crop.json, preview.jpg, final.mp4}
│   └── exports/
├── scripts/
│   ├── setup.(sh|ps1)           # cria venv, instala deps, builda frontend
│   └── start.(sh|bat)           # sobe API + worker
├── run.py                       # inicia API e worker juntos (subprocess)
├── DECISIONS.md
└── README.md
```

---

## 5. Modelo de dados (SQLModel)

```text
Download
  id, url, title, uploader, duration_s, thumbnail_url,
  format_choice ("best" | "1080p" | "720p" | "audio_mp3"),
  status ("queued"|"downloading"|"done"|"error"|"canceled"),
  progress (0-100), speed, eta, file_path, filesize, error,
  project_id (nullable — se foi enviado para cortes), created_at

Project                         # um vídeo-fonte que vai virar cortes
  id, name, source_path, origin ("download"|"upload"|"local_path"),
  duration_s, width, height, fps,
  language (default "pt"),
  status ("new"|"processing"|"ready"|"error"),
  stage ("probe"|"proxy"|"transcribe"|"analyze"|"done"),
  settings_json   # opções da análise: nº de cortes, duração min/max, prompt extra
  created_at

Clip
  id, project_id, title, hook_text, reason,
  start_s, end_s,                 # editáveis
  score (0-100), score_breakdown_json  # {gancho, emoção, clareza, completude}
  status ("suggested"|"edited"|"rendering"|"rendered"|"error"|"discarded"),
  reframe_mode ("auto"|"center"|"blur_fit"|"split"|"manual"),
  manual_crop_json,               # keyframes de crop definidos no editor
  caption_style_id, caption_overrides_json, # textos corrigidos pelo usuário
  title_overlay (texto fixo no topo, opcional),
  output_path, created_at, updated_at

CaptionStyle                    # presets de legenda
  id, name, font, font_size, primary_color, highlight_color,
  outline_color, outline_px, shadow_px, uppercase (bool),
  words_per_line (1-4), position_y (0-1), animation ("highlight"|"pop"|"none"),
  is_builtin

Job
  id, type ("download"|"probe_proxy"|"transcribe"|"analyze"|"reframe"|"render"),
  ref_id (download_id/project_id/clip_id), status ("queued"|"running"|"done"|"error"|"canceled"),
  progress, message, error, uses_gpu (bool), priority,
  created_at, started_at, finished_at
```

Arquivos grandes (transcrição, rostos, peaks) ficam como **JSON em disco**, não no banco.

---

## 6. API (REST + SSE)

Prefixo `/api`.

### Downloads
- `POST /downloads/info` `{url}` → metadados sem baixar (título, duração, thumb, formatos disponíveis). Usa `yt_dlp.YoutubeDL({"skip_download": True}).extract_info`.
- `POST /downloads` `{url, format_choice, send_to_project: bool}` → cria Download + Job.
- `GET /downloads` → histórico.
- `POST /downloads/{id}/cancel`, `DELETE /downloads/{id}` (com opção de apagar o arquivo).
- `POST /downloads/{id}/to-project` → cria Project a partir do arquivo baixado.
- Suporte a **playlist**: `info` detecta e retorna lista; o usuário marca quais baixar.

### Projetos
- `POST /projects` → a partir de `download_id`, **upload** (multipart, streaming em chunks) ou **caminho local** (`local_path`, para não copiar arquivos enormes).
- `GET /projects`, `GET /projects/{id}`, `DELETE /projects/{id}`.
- `POST /projects/{id}/analyze` `{num_clips, min_s, max_s, extra_prompt, language}` → enfileira probe_proxy → transcribe → analyze (encadeados).
- `GET /projects/{id}/transcript` → palavras com tempo.
- `PUT /projects/{id}/transcript` → correções manuais de palavras.

### Cortes
- `GET /projects/{id}/clips`
- `POST /projects/{id}/clips` → criar corte manual (start/end escolhidos pelo usuário).
- `PATCH /clips/{id}` → qualquer campo editável.
- `POST /clips/{id}/render`, `POST /projects/{id}/render-all` (só os não descartados).
- `POST /clips/{id}/duplicate`, `DELETE /clips/{id}`.
- `GET /clips/{id}/crop-track` → trilha de crop calculada (para preview no editor).

### Jobs / sistema
- `GET /jobs`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry`.
- `GET /events` → **SSE**: eventos `job.update`, `download.update`, `clip.update`, `project.update`.
- `GET /system/check` → ffmpeg, ffprobe, libass, ollama online, modelo presente, CUDA, NVENC, espaço em disco.
- `GET/PUT /system/settings`.
- `GET /caption-styles`, `POST/PATCH/DELETE /caption-styles/{id}`.
- `GET /media/{path}` → streaming com **suporte a HTTP Range** (obrigatório para o `<video>` permitir seek). Restringir a paths dentro de `data/`.

---

## 7. Worker e fila

- Processo separado (`python -m app.worker.runner`) que faz polling no SQLite a cada ~0,5 s.
- **Dois "slots"**: um para jobs leves de I/O (download, probe) — até 2 simultâneos; outro para jobs pesados (`uses_gpu=True`: transcribe, analyze, reframe, render) — **1 por vez**, para não estourar VRAM.
- Cada handler recebe um `report(progress, message)` que atualiza o Job no banco; a API lê mudanças e publica no SSE.
- Cancelamento: o handler checa `job.status == "canceled"` entre etapas; subprocessos ffmpeg são guardados para `terminate()`.
- Jobs em `running` quando o app reinicia voltam para `queued`.
- Modelos (Whisper) ficam **carregados em cache no worker** entre jobs; liberar VRAM antes de chamar o Ollama se a GPU tiver < 10 GB (`del model; torch.cuda.empty_cache()` ou recriar o `WhisperModel`).

---

## 8. Pipeline em detalhe

### 8.1 Download (`services/downloader.py`)
- `yt_dlp.YoutubeDL` com `progress_hooks` → `report()`.
- Formatos:
  - `best`: `bv*+ba/b`, merge para mp4 (`merge_output_format: "mp4"`).
  - `1080p`: `bv*[height<=1080]+ba/b[height<=1080]`.
  - `720p`: idem com 720.
  - `audio_mp3`: `ba` + postprocessor FFmpegExtractAudio mp3 192k.
- Template de saída: `data/downloads/%(title).80s [%(id)s].%(ext)s`, nomes sanitizados (`restrictfilenames` desligado, mas `windowsfilenames: True`).
- Salvar título, uploader, duração, thumb.
- Erros comuns (vídeo privado, idade, geobloqueio) → mensagem amigável em PT-BR.
- Botão em Configurações: **"Atualizar yt-dlp"** (roda `pip install -U yt-dlp`), porque sites mudam com frequência.
- Opcional: campo para `cookies.txt` (sites que pedem login).

### 8.2 Probe + proxy (`services/probe.py`, `proxy.py`)
- `ffprobe -v error -show_streams -show_format -of json` → duração, resolução, fps, codec, se tem áudio.
- Proxy para o editor: 540p, h264 `-preset veryfast -crf 28`, keyframe a cada 1 s (`-g <fps>`) para seek rápido.
- Áudio: `ffmpeg -i source -ac 1 -ar 16000 audio.wav` (entrada do Whisper).
- Waveform: calcular picos (ex.: 100 por segundo) com numpy a partir do wav → `waveform.json` (wavesurfer aceita `peaks` prontos — evita decodificar áudio grande no navegador).
- Thumbnails: um frame a cada 10 s para a tira da timeline (sprite opcional).

### 8.3 Transcrição (`services/transcriber.py`)
```python
from faster_whisper import WhisperModel
# GPU: ("large-v3", device="cuda", compute_type="float16")  |  VRAM < 6GB: ("medium", "cuda", "int8_float16")
# CPU: ("small", device="cpu", compute_type="int8")  (permitir trocar em Configurações)
segments, info = model.transcribe(
    "audio.wav", language=lang_or_None, word_timestamps=True,
    vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
    beam_size=5,
)
```
- Progresso = `segment.end / duração`.
- Salvar `transcript.json`:
```json
{"language":"pt","segments":[{"id":0,"start":0.0,"end":4.2,"text":"...",
  "words":[{"w":"Olha","s":0.0,"e":0.31,"p":0.98}]}]}
```
- Pós-processamento: remover palavras com duração 0, juntar pontuação solta à palavra anterior.

### 8.4 Detecção de destaques (`services/highlighter.py`)

**a) Preparação**
- Converter a transcrição em linhas numeradas com tempo: `[123.4–127.9] texto da frase`.
- Vídeos longos: janelas de ~8 min com 1 min de sobreposição. Para cada janela, pedir ao LLM até `ceil(num_clips * 1.5 / n_janelas) + 1` candidatos.

**b) Chamada ao Ollama** (`POST http://localhost:11434/api/chat`, `stream: false`, `format: <JSON schema>`, `options: {temperature: 0.3, num_ctx: 8192}`):

Prompt de sistema (PT-BR):
```
Você é um editor especialista em vídeos curtos virais (TikTok, Reels, Shorts).
Receberá a transcrição de um trecho de vídeo com timestamps.
Encontre os melhores momentos para virar cortes independentes de {min_s} a {max_s} segundos.
Um bom corte:
- começa com um GANCHO forte nos primeiros 3 segundos (pergunta, afirmação polêmica, número, promessa, conflito);
- é compreensível sozinho, sem contexto do resto do vídeo;
- tem começo, meio e fim (termina numa conclusão, punchline ou frase completa);
- tem emoção, humor, opinião forte, história ou informação valiosa.
Evite: introduções, pedidos de inscrição, trechos que dependem do que veio antes.
Use APENAS timestamps que existem na transcrição.
{extra_prompt_do_usuario}
Responda somente no JSON pedido.
```
Schema de saída:
```json
{"clips":[{"start":0.0,"end":0.0,"title":"string (até 60 caracteres, chamativo)",
  "hook":"string (primeira frase do corte)","reason":"string",
  "scores":{"gancho":0,"emocao":0,"clareza":0,"completude":0}}]}
```

**c) Pós-processamento (determinístico, em Python)**
- Validar JSON; se falhar, tentar de novo 1× com temperatura 0.
- **Ajustar bordas**: mover `start` para o início da palavra/frase mais próxima e `end` para o fim de frase mais próximo (pontuação `.?!` ou pausa > 0,4 s). Adicionar 0,15 s de respiro no fim.
- Forçar duração entre `min_s` e `max_s` (estender/encurtar até a próxima borda de frase).
- Remover sobreposições > 50% (fica o de maior nota).
- **Nota final (0–100)** = 0,75 × média ponderada das notas do LLM (gancho 35%, completude 25%, emoção 25%, clareza 15%) + 0,25 × heurística:
  - energia de áudio (RMS médio do trecho vs. média do vídeo),
  - ritmo de fala (palavras/s perto de 2,5–3,5 é bom),
  - poucos silêncios longos.
- Ordenar por nota e salvar os N melhores como `Clip(status="suggested")`.

### 8.5 Reenquadramento 9:16 (`services/reframer.py`)

Pré-análise por projeto (feita uma vez, reutilizada por todos os cortes):
- **Cenas**: PySceneDetect `ContentDetector` → `scenes.json` (lista de cortes de câmera).
- **Rostos**: ler o proxy a ~5 fps com OpenCV, MediaPipe Face Detection (modelo full-range, confiança ≥ 0,5) → `faces.json` com bounding boxes normalizadas por tempo.

Por corte, gerar uma **trilha de crop** (centro X por frame, largura fixa = altura × 9/16):
1. Para cada amostra, escolher o rosto-alvo: o maior; se houver vários, preferir o que **move a boca** (variação dos landmarks dos lábios — opcional/v2) ou o que mais apareceu na cena.
2. Sem rosto → manter o último centro; se nunca houve rosto na cena → centro da tela.
3. **Suavização**: zona morta (só move se o alvo sair de ±8% da largura do crop), depois suavização exponencial (α ≈ 0,1 por amostra) ou filtro de Savitzky-Golay. **Na troca de cena, reiniciar sem suavizar** (salto seco, como câmera real).
4. Interpolar para o fps do vídeo, limitar aos bordos do quadro.
5. Salvar `crop.json` (o editor mostra esse retângulo sobre o preview e permite sobrescrever com keyframes manuais).

Modos:
- `auto`: trilha acima.
- `center`: crop central fixo.
- `blur_fit`: vídeo inteiro centralizado (largura total) sobre fundo do próprio vídeo ampliado e borrado — bom para telas/gameplay.
- `split`: dois rostos → metade de cima e metade de baixo (quando houver 2 rostos estáveis na maior parte do corte).
- `manual`: keyframes do usuário, interpolados linearmente com easing.

Aplicação do crop no render: para crop **variável**, ler frames da fonte com OpenCV (na resolução original), recortar, redimensionar para 1080×1920 e enviar raw (`bgr24`) para o stdin do ffmpeg; o áudio vem do arquivo original com `-ss/-to`. Para `center`/`blur_fit`, usar só filtros ffmpeg (mais rápido).

### 8.6 Legendas (`services/captions.py`)
- Entrada: palavras do corte (tempos relativos ao `start` do corte), com correções do usuário aplicadas.
- Agrupar em linhas de `words_per_line` palavras (quebrar também em pontuação e pausas > 0,35 s; máx. ~18 caracteres por linha).
- Gerar **ASS** com `PlayResX=1080, PlayResY=1920`:
  - `highlight`: para cada palavra, um evento `Dialogue` mostrando a linha inteira com a palavra atual em `highlight_color` (via override `{\c&HBBGGRR&}`) — as cores no ASS são **BGR**.
  - `pop`: palavra atual com `{\fscx115\fscy115}` → animação `\t` de volta a 100.
  - `uppercase`, contorno, sombra, posição vertical (`\pos` ou `MarginV`).
- `title_overlay` vira um segundo estilo no topo, durante o corte todo (ou só os 3 primeiros segundos — opção).
- Presets embutidos (criar no primeiro start):
  - **Hormozi**: Montserrat ExtraBold, branco, destaque amarelo `#FFE600`, contorno preto 6px, maiúsculas, 2 palavras.
  - **Clean**: Inter Bold, branco, sombra suave, 4 palavras, sem destaque.
  - **Neon**: destaque verde `#39FF14`, pop.
  - **Karaokê**: palavras já faladas mudam de cor.
- Fontes: incluir `.ttf` livres (Montserrat, Inter, Bebas Neue — licença OFL) em `backend/assets/fonts/` e passar `fontsdir` no filtro `ass`.
- **Atenção Windows**: no filtro `ass=`, o caminho precisa de escape (`C\:/pasta/arquivo.ass`). Mais seguro: rodar o ffmpeg com `cwd` na pasta do corte e usar caminho relativo `ass=captions.ass:fontsdir=fonts`.

### 8.7 Render (`services/renderer.py`)
- Saída: 1080×1920, 30 fps (ou fps da fonte se ≤ 60), H.264, AAC 48 kHz 192k, `-movflags +faststart`.
- Encoder: `h264_nvenc -preset p5 -cq 21` se NVENC disponível; senão `libx264 -preset veryfast -crf 20`.
- Áudio: `loudnorm=I=-14:TP=-1.5:LRA=11` (padrão das redes) — opção ligada por padrão.
- Corte preciso: `-ss` **depois** do `-i` para o vídeo (ou antes + re-encode), garantindo sincronia com as legendas.
- Gerar `preview.jpg` (frame do meio) e salvar `output_path`.
- Nome do arquivo final: `<nota>_<titulo-slug>.mp4` em `data/exports/<projeto>/`.
- Progresso: parsear `-progress pipe:1` do ffmpeg (`out_time_ms`).

### 8.8 Hardware (`services/hardware.py`)
- CUDA: `ctranslate2.get_cuda_device_count() > 0`.
- NVENC: `ffmpeg -hide_banner -encoders` contém `h264_nvenc` **e** um teste rápido de encode de 1 frame funciona.
- VRAM: `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` (se existir).
- Escolher defaults (modelo Whisper, compute_type, encoder) a partir disso; tudo sobrescrevível em Configurações.

---

## 9. Interface (frontend)

Layout: barra lateral fixa com **Downloads · Projetos · Fila · Configurações**. Tema escuro por padrão. Tudo em PT-BR. Toasts para sucesso/erro. Atualizações via SSE (sem refresh manual).

### 9.1 Downloads
- Campo grande "Cole o link aqui" + botão **Analisar** → card com thumb, título, canal, duração.
- Seletor de qualidade (Melhor / 1080p / 720p / Só áudio MP3) e checkbox **"Enviar para cortes após baixar"**.
- Playlist: lista com checkboxes + "Selecionar todos".
- Lista/histórico: barra de progresso, velocidade, ETA, status; ações: cancelar, abrir pasta, **Criar cortes**, apagar.
- Aceitar vários links de uma vez (um por linha).

### 9.2 Projetos
- Grade de cards (thumb, nome, duração, nº de cortes, status/etapa com progresso).
- Botão **Novo projeto**: a partir de download / upload (drag & drop) / caminho local.
- Ao criar, modal **"Configurar análise"**: nº de cortes (padrão 10), duração mín/máx (padrão 20–60 s), idioma, preset de legenda padrão, modo de enquadramento padrão, "instruções extras para a IA" (ex.: "foque nas partes engraçadas").

### 9.3 Projeto (lista de cortes sugeridos)
- Player do vídeo original (proxy) à esquerda; à direita, lista de cortes ordenada por nota:
  - badge de nota colorido (verde ≥ 80, amarelo ≥ 60, cinza abaixo), título, duração, gancho, motivo (expandível).
  - Clicar → toca o trecho no player.
  - Ações: **Editar**, **Renderizar**, **Descartar**, **Duplicar**.
- Botões: **Renderizar todos**, **Novo corte manual**, **Reanalisar** (com outras opções).
- Filtro: nota mínima, status.

### 9.4 Editor de corte (a tela principal)

```
┌──────────────────────────────────────────────────────────────────────┐
│ ← Voltar   Título do corte [editável]              Nota 87   [Renderizar] │
├───────────────────────┬───────────────────────┬──────────────────────┤
│  Fonte 16:9 (proxy)   │  Preview 9:16         │  Painel lateral      │
│  com retângulo de     │  (crop + legenda      │  (abas)              │
│  crop arrastável      │   simulados em CSS)   │  • Legenda           │
│                       │                       │  • Enquadramento     │
│                       │                       │  • Texto/Título      │
│                       │                       │  • Exportar          │
├───────────────────────┴───────────────────────┴──────────────────────┤
│ Timeline: forma de onda + tira de thumbs, região do corte com alças   │
│ de início/fim, playhead, zoom; contexto ±30 s fora do corte           │
├──────────────────────────────────────────────────────────────────────┤
│ Transcrição do corte: palavras clicáveis (clique = seek;              │
│ Shift+clique = definir início/fim; duplo clique = corrigir palavra)   │
└──────────────────────────────────────────────────────────────────────┘
```

Requisitos do editor:
- **Preview sem renderizar**: o `<video>` do proxy é exibido dentro de um container 9:16 usando `object-position`/transform calculados pela trilha de crop no `timeupdate`/`requestAnimationFrame`; a legenda é desenhada em HTML/CSS por cima, imitando o estilo ASS (mesma fonte, cores, contorno via `-webkit-text-stroke`/`text-shadow`, destaque da palavra atual). Deve ser **fiel o suficiente** para o usuário decidir sem renderizar.
- Timeline com wavesurfer.js + Regions: arrastar alças muda `start_s`/`end_s`; ao soltar, "grudar" na borda de palavra mais próxima (desligável com Alt).
- Transcrição: palavras fora do corte ficam acinzentadas; corrigir texto de palavra salva em `caption_overrides_json` (não altera tempos).
- Aba **Legenda**: escolher preset, editar fonte/tamanho/cores/palavras por linha/posição/maiúsculas/animação; "Salvar como novo preset".
- Aba **Enquadramento**: modo (auto/centro/blur/split/manual); no manual, arrastar o retângulo na fonte e clicar **"Adicionar keyframe"** no tempo atual; lista de keyframes com remover.
- Aba **Texto/Título**: título fixo no topo (liga/desliga, só nos primeiros 3 s ou o corte todo).
- Aba **Exportar**: qualidade, normalizar áudio, botão renderizar, link para abrir o arquivo/pasta após terminar.
- **Autosave** com debounce (800 ms) via `PATCH /clips/{id}`; desfazer/refazer (Ctrl+Z / Ctrl+Shift+Z) no store Zustand.
- Atalhos: Espaço (play/pause), J/K/L, ←/→ (1 frame / Shift = 1 s), I/O (definir início/fim no playhead), Ctrl+S (forçar salvar), Ctrl+Enter (renderizar).

### 9.5 Fila
- Tabela de jobs com tipo, alvo, progresso, mensagem, duração; cancelar/repetir; filtro por status.

### 9.6 Configurações
- **Diagnóstico** (seção 3) com botão "Verificar novamente".
- Modelo Whisper (tiny…large-v3, auto), dispositivo (auto/cuda/cpu), compute type.
- URL do Ollama + seletor de modelo (lista via `GET /api/tags` do Ollama) + botão "Testar".
- Encoder (auto/nvenc/x264), pasta de exportação, idioma padrão.
- Atualizar yt-dlp; caminho de `cookies.txt`.
- Uso de disco de `data/` + botão "Limpar arquivos temporários" (proxies/wav de projetos antigos).

---

## 10. Requisitos não funcionais

- **Tudo local**: nenhuma chamada externa além do download de vídeos e do download inicial de modelos.
- **Resiliência**: cada etapa salva o resultado em disco; reanalisar ou re-renderizar **não** refaz etapas já prontas (cache por existência de arquivo + hash das opções).
- **Desempenho alvo** (vídeo de 1 h, GPU de 8 GB): transcrição < 5 min, análise < 3 min, render de cada corte de 45 s < 30 s.
- **Sem GPU** precisa funcionar — só mais devagar. Mostrar estimativa de tempo antes de analisar.
- Logs em `data/logs/` (rotação), nível configurável. Erros de job mostram a causa em PT-BR + detalhe técnico expansível.
- Caminhos com acento/espaço devem funcionar (Windows principalmente). Usar `pathlib` sempre.
- Segurança básica: API escuta só em `127.0.0.1`; `/media` não pode servir nada fora de `data/` (bloquear `..`).

---

## 11. Testes

- `pytest` no backend:
  - `captions.py`: agrupamento de palavras, cores BGR, tempos relativos.
  - `highlighter.py`: ajuste de bordas, remoção de sobreposição, clamp de duração, parse de JSON inválido (com LLM mockado).
  - `reframer.py`: suavização, reset em troca de cena, limites do quadro (com dados sintéticos).
  - `renderer.py`: montagem do comando ffmpeg (sem executar).
  - Teste de integração com um vídeo curto gerado por ffmpeg (`testsrc` + `sine`) cobrindo probe → render.
- Frontend: `vitest` para utilitários (cálculo de crop no preview, agrupamento de legenda — **mesma lógica do backend**, idealmente compartilhando casos de teste em JSON).

---

## 12. Fases de implementação

Cada fase termina com o app rodando e os critérios atendidos.

**Fase 0 — Esqueleto**
- Estrutura de pastas, FastAPI com `/api/system/check`, frontend Vite + Tailwind + shadcn com layout e rotas vazias, `run.py` subindo API + worker, scripts de setup/start.
- ✅ `python run.py` abre a UI em localhost:8000 e a tela de Configurações mostra o diagnóstico real.

**Fase 1 — Downloads**
- Tabelas, worker/fila, SSE, downloader com progresso, página Downloads completa (incl. playlist e múltiplos links).
- ✅ Colar um link do YouTube, ver progresso em tempo real, arquivo aparece em `data/downloads/`, cancelar funciona.

**Fase 2 — Projetos + transcrição**
- Criar projeto (download/upload/caminho local), probe, proxy, wav, waveform, transcrição com progresso; endpoint `/media` com Range.
- ✅ Vídeo de 10 min vira projeto e a transcrição com palavras aparece na tela do projeto.

**Fase 3 — Destaques**
- highlighter com Ollama + pós-processamento + nota; lista de cortes sugeridos na página do projeto, tocando o trecho no player.
- ✅ Gera N cortes coerentes, com bordas em fim de frase, sem sobreposição, ordenados por nota.

**Fase 4 — Render básico**
- Render com crop central + legenda ASS (preset Hormozi) + loudnorm + NVENC/x264; página Fila.
- ✅ "Renderizar todos" produz MP4s 1080×1920 que tocam no celular com legenda sincronizada.

**Fase 5 — Reenquadramento**
- Cenas + rostos + trilha suavizada; modos auto, blur_fit, split.
- ✅ Em um podcast com 2 pessoas, o crop segue quem aparece sem tremer, e salta seco nas trocas de câmera.

**Fase 6 — Editor**
- Tela de editor completa (seção 9.4): preview com crop e legenda simulados, timeline com alças, transcrição clicável, abas, autosave, desfazer, atalhos, keyframes manuais.
- ✅ Ajustar início/fim, trocar estilo e corrigir uma palavra reflete no preview na hora e no MP4 final.

**Fase 7 — Acabamento**
- Presets extras, título no topo, corte manual do zero, limpeza de temporários, estimativa de tempo, mensagens de erro amigáveis, README com instalação passo a passo para leigos.
- ✅ Um usuário novo consegue instalar seguindo só o README.

**Ideias para depois (v2)**
- Detecção de quem está falando (diarização com pyannote ou movimento labial) para o crop seguir a voz.
- B-roll/emoji automáticos, zoom punch-in nas palavras de ênfase.
- Remoção de silêncios e "éé/hum" (jump cuts).
- Tradução de legenda, empacotar como app desktop (Tauri/PyInstaller).
- Integração com o "studio de IA" (outros módulos de automação no mesmo app).

---

## 13. Observação de uso

Baixe e corte apenas conteúdo que você tem direito de usar (seu, com licença ou com permissão do criador). Algumas plataformas monetizam cortes de terceiros só com autorização.
