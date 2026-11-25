# Decisões

Registro de escolhas onde a especificação era ambígua ou o ambiente exigiu adaptação.

## Fase 0
- **Ambiente de referência**: Ubuntu 26.04, RTX 3050 8 GB. Python do sistema é 3.14 sem `ensurepip`;
  MediaPipe/ctranslate2 costumam atrasar wheels para versões novas do Python → o projeto usa
  **Python 3.12 via `uv`** (fallback: `python3.11+ -m venv`).
- **Ambiente virtual** fica em `.venv/` na raiz; `scripts/start.sh` usa esse Python.
- **Logging**: `setup_logging()` em `app/logging_setup.py` (separado de `main.py` para o worker
  não importar o FastAPI). Arquivos em `data/logs/{api,worker}.log`, rotação 5 MB × 3.
- **Configuração**: infraestrutura via env `MDC_*` (`MDC_PORT`, `MDC_DATA_DIR`...);
  preferências do usuário em `data/settings.json` (GET/PUT `/api/system/settings`).
- **Modo dev**: `python run.py --dev` sobe também o Vite em :5173 com proxy de `/api` → :8000.
- **shadcn/ui**: componentes base (button, card, badge) escritos à mão no padrão shadcn
  (Tailwind v4 + `cn()`), com `components.json` para que `npx shadcn add <x>` funcione depois.
- **Toasts**: `sonner` (é o que o shadcn recomenda).
- **NVENC**: considerado disponível só se um encode real de 1 frame funcionar (resultado em cache
  por processo).

## Instalação do ambiente (sem sudo)
- Tudo instalado no espaço do usuário, sem `sudo`:
  - `uv` → `~/.local/bin/uv`; Python 3.12 gerenciado pelo uv; venv em `.venv/`.
  - **FFmpeg 8.1 estático** (BtbN/FFmpeg-Builds, GPL) em `~/.local/opt/`, links em `~/.local/bin/{ffmpeg,ffprobe}`.
    Tem libass e NVENC (o ffmpeg do apt do Ubuntu não tem NVENC).
  - **Ollama** (tarball oficial) em `~/.local/opt/ollama`, link em `~/.local/bin/ollama`. Modelos em `~/.ollama`.
- `run.py` prepara o ambiente dos processos filhos: coloca `~/.local/bin` no PATH, adiciona as libs
  `nvidia/*/lib` do venv ao `LD_LIBRARY_PATH` (cuBLAS 12 / cuDNN 9 para o ctranslate2) e **sobe o
  `ollama serve` se não estiver rodando** (e o encerra ao sair, só se foi ele que subiu). Log em `data/logs/ollama.log`.
- Diagnóstico de CUDA só fica ✅ se `libcublas.so.12` e `libcudnn.so.9` carregam de verdade.
- `av<17`: PyAV 17+ removeu o argumento `metadata_errors` que o faster-whisper 1.2.1 usa.
- Todas as dependências Python das fases 1–5 já instaladas de antemão (requirements.txt completo).
- Modelos pré-baixados: `qwen2.5:7b` (Ollama) e Whisper `large-v3` (cache do Hugging Face).
- Fontes de legenda **estáticas** (não variáveis — o libass resolve mal pesos de fontes variáveis):
  Montserrat Bold/ExtraBold/Black, Inter SemiBold/Bold/ExtraBold, Bebas Neue (todas OFL).
- `mediapipe` puxa `opencv-python` junto com o `-headless`; ambos coexistem por ora — revisar na Fase 5 se houver conflito.
- **VRAM (RTX 3050 8 GB)**: `qwen2.5:7b` ocupa ~4,6 GB e Whisper `large-v3` fp16 ~3,7 GB — **não cabem juntos**
  (testado: OOM). Regra para o worker (Fase 2/3): antes de transcrever, descarregar o modelo do Ollama
  (`POST /api/generate {"model": ..., "keep_alive": 0}`); depois de transcrever, liberar o Whisper antes de
  chamar o LLM. Jobs de GPU já rodam 1 por vez (seção 7).

## Fase 1 — Downloads
- **Fila** = tabela `job`. `app/queue.py` concentra enfileirar/cancelar/repetir/claim (claim atômico via
  `UPDATE … WHERE status='queued'`). Worker: `ThreadPoolExecutor` leve (2) + GPU (1).
- **Cancelamento**: a API marca `canceled`; o loop do worker (0,5 s) vê que o job não está mais `running`
  (cancelado *ou apagado*) e chama `JobContext.cancel()` → evento + `terminate()` dos subprocessos.
  O hook de progresso do yt-dlp checa o evento e aborta; arquivos `.part`/fragmentos são apagados.
- **Encerramento do app** ≠ cancelamento: jobs em andamento voltam para `queued` (e o download para `queued`)
  e são retomados ao reiniciar. Se o worker morrer sem encerrar, o `recover_interrupted()` do start faz o mesmo.
- **SSE**: a API não recebe nada do worker diretamente; um polling de `updated_at` (0,5 s, janela de 1 s
  com deduplicação por `(tabela, id, updated_at)`) publica `job.update`/`download.update`. O front aplica
  os eventos direto no cache do TanStack Query e invalida tudo ao reconectar.
- **Datas** em UTC com timezone (o SQLModel atual exige datetime "aware").
- **YouTube** exige resolver desafios JS: `yt-dlp[default]` (inclui `yt-dlp-ejs`) + runtime `node`
  (o padrão do yt-dlp é `deno`, que não está instalado). `base_opts()` habilita os que existirem.
- **Progresso DASH**: vídeo e áudio são baixados em sequência; os formatos são resolvidos antes
  (`extract_info(download=False)` → `process_ie_result`) e o progresso é ponderado pelo tamanho de cada parte.
  100% só quando o job termina (pós-processamento fica em 99%).
- **Lote**: `POST /downloads/batch` (vários links/entradas de playlist numa chamada), além do `POST /downloads`.
- **Erros** do yt-dlp viram mensagem PT-BR (`friendly_error`) + detalhe técnico expansível na UI.
- **"Enviar para cortes"** já é gravado (`Download.send_to_project`), mas a criação do projeto chega na Fase 2;
  o botão "Criar cortes" fica desabilitado até lá.
- **Abrir pasta**: `POST /system/open-folder` (xdg-open/open/explorer), restrito a `data/`.
- **Atualizar yt-dlp**: `uv pip install -U yt-dlp[default]` (ou pip); requer reiniciar o app.
- Apagar um download apaga também seus jobs; "lista + arquivo" recusa se o arquivo pertencer a um projeto.

## Fase 2 — Projetos + transcrição
- **Fonte sem cópia**: projetos de download e de caminho local apontam para o arquivo original
  (`source_path`); só o upload é gravado em `data/projects/<id>/source.<ext>`. Apagar um projeto remove
  só a pasta dele (derivados + upload). Um download com projeto não pode ter o arquivo apagado.
- **Upload** em streaming com corpo cru (`POST /projects/upload?filename=…`, sem multipart) e progresso via XHR.
- **"Criar cortes"** (Downloads) = `POST /downloads/{id}/to-project` → abre o projeto com `?configurar=1`,
  que mostra o modal "Configurar análise". Downloads só de áudio não viram projeto.
- **Pipeline**: `probe_proxy` (slot leve) → `transcribe` (slot GPU). O job `analyze` entra na Fase 3; por ora
  o projeto fica `ready` após a transcrição. Opções da análise ficam em `settings_json`.
- **Cache**: `meta.json` guarda a assinatura da fonte (caminho+tamanho+mtime); reanalisar não refaz proxy/wav/
  waveform/thumbs. A transcrição é reaproveitada se o idioma pedido for o mesmo.
- **Proxy** com NVENC quando disponível (cai para libx264 se falhar); keyframe a cada ~1 s; altura máx. 540.
- **Waveform**: picos absolutos normalizados, 100/s, lidos do WAV em blocos de 1 min (memória constante).
- **Whisper**: `auto` → large-v3/float16 na GPU (≥ 6 GB), senão CPU small/int8; se carregar na GPU falhar,
  cai para CPU. Antes de transcrever na GPU, descarrega os modelos do Ollama (`/api/ps` + `keep_alive: 0`).
  O modelo fica em cache no worker entre jobs (`release_model()` existe para a Fase 3).
- **Correção de transcrição** (`PUT /transcript`) só altera o texto das palavras; tempos/estrutura são preservados.
- **IDs reaproveitados**: o SQLite reutiliza ids de projetos apagados, então apagar um projeto apaga todos os
  jobs dele; o worker interrompe um job em execução cujo registro sumiu.
- **/media**: `FileResponse` do Starlette já responde Range (206); caminho resolvido e restrito a `data/`.

## Fase 3 — Destaques
- **Encadeamento**: `transcribe` → `analyze` (slot GPU). Antes do LLM, o worker libera o Whisper se a GPU tiver
  < 10 GB (ou não for detectada); antes de transcrever, descarrega o Ollama. Os dois nunca ficam juntos na VRAM.
- **Ollama** via `/api/chat` em **streaming** com `format` = JSON schema (permite cancelar no meio da geração e
  mostrar progresso por janela). `num_ctx 8192`, temperatura 0,3 → se o JSON vier inválido, repete 1× com 0.
- Notas do LLM pedidas de **0 a 10** (o spec mostra `0` sem escala); valores > 10 são tratados como escala 0–100.
  Nota final = 0,75 × LLM ponderado (gancho 35 / completude 25 / emoção 25 / clareza 15, ×10) + 0,25 × heurística
  (média de energia RMS vs. média do vídeo, ritmo 2,5–3,5 palavras/s e silêncios > 0,7 s).
- **Bordas**: frase = termina em `.?!…` ou pausa > 0,4 s. Início/fim grudam na borda de frase mais próxima (raio 4 s);
  depois de ajustar a duração, se o fim ainda cair no meio de frase, troca pelo fim de frase mais próximo que respeite
  [mín, máx] (sem limite de raio). Respiro de 0,15 s no fim, sem invadir a palavra seguinte.
- **Sobreposição** medida em relação ao corte mais curto; > 50% → fica o de maior nota.
- `hook_text` = primeira frase real do corte (após o ajuste), não o "hook" do LLM, que pode não bater com as bordas.
- **Reanálise** apaga só cortes da IA ainda `suggested`/`discarded`; editados, renderizados e manuais ficam.
- **Corte manual**: `origin="manual"`, `status="edited"`, nota 0 (mostrado como "manual" na lista).
- Observação de qualidade (qwen2.5:7b): as notas ficam comprimidas (quase tudo 80–89, o LLM dá gancho 9 a quase
  tudo). A ordem ainda é útil; se incomodar, dá para normalizar por ranking na Fase 7.
- Desempenho medido: vídeo de 17,8 min (3 janelas) → análise em ~75 s na RTX 3050.

## Fase 4 — Render básico
- **Migração automática**: `init_db()` compara modelos × tabelas e faz `ALTER TABLE ADD COLUMN` com o default
  do modelo (o `create_all` não altera tabelas existentes). Não remove/renomeia colunas.
- **CaptionStyle**: presets embutidos (`key` = hormozi/clean/neon/karaoke) criados no start; não editáveis —
  "salvar como novo preset" cria um estilo do usuário. Cores guardadas como `#RRGGBB`; a conversão para BGR do ASS
  fica no `captions.py`. Estilo do corte: `caption_style_id` → senão o preset escolhido na análise → Hormozi.
- **Animação "karaoke"** adicionada (o spec lista highlight/pop/none, mas o preset Karaokê precisa dela).
- **Legenda**: posição por `\an5\pos(540, position_y×1920)`; linhas quebram por nº de palavras, pontuação,
  pausa > 0,35 s ou > 18 caracteres; a linha fica na tela até a próxima se o intervalo for ≤ 0,6 s.
  Correções por corte em `caption_overrides_json` = `{"<início da palavra com 3 casas>": "texto"}` (texto vazio
  apaga a palavra da legenda). `title_overlay` aparece no topo numa caixa branca durante o corte todo.
- **Fontes** conferidas no log do libass (`fontselect`): Montserrat ExtraBold/Black e Inter casam com os .ttf
  do `assets/fonts` (sem fallback). ffmpeg roda com `cwd` na pasta do corte e `ass=captions.ass:fontsdir=<abs>`
  (valor escapado para filtergraph).
- **Corte preciso**: `-ss` antes do `-i` + re-encode (preciso e rápido; timestamps começam em 0 = tempos do .ass).
- **Enquadramento**: `center` (maior retângulo 9:16 centralizado; funciona também com fonte vertical) e `blur_fit`
  só com filtros. `auto`/`split`/`manual` usam `center` até a Fase 5.
- **Encoder**: NVENC p5 cq21 / x264 veryfast crf20, ambos com **teto de 8 Mbps** (sem teto davam ~15 Mbps em
  fonte 720p ampliada). Falha no NVENC → tenta x264. fps = fonte se ≤ 60, senão 30. Áudio loudnorm −14 LUFS
  (opção `normalize_audio` nas configurações), AAC 48 kHz 192k, `+faststart`.
- **Cache do render**: hash de (spec + .ass + assinatura da fonte + `RENDER_VERSION`) em `clips/<id>/render.json`;
  igual e MP4 existe → não renderiza. Mudou título/nota → arquivo renomeado e o antigo apagado.
- **Saída**: `<export_dir ou data/exports>/<projeto-slug>-<id>/<nota>_<titulo-slug>.mp4` (sufixo `_<id>` só se
  outro corte já usar o nome). `GET /clips/{id}/file` serve o MP4 (Range; `?download=1` para baixar).
- Editar um corte renderizado → status `edited` (UI mostra "MP4 desatualizado").
- `run.py`: uvicorn com `--timeout-graceful-shutdown 3` (conexões SSE abertas seguravam o desligamento).
- Medido (RTX 3050, fonte 720p60): 10 cortes de 23–60 s em 123 s (7–16 s cada); −14,4 LUFS; legenda sincronizada.

## Fase 5 — Reenquadramento
- **Detector de rosto: YuNet (OpenCV `FaceDetectorYN`)**, não MediaPipe. O MediaPipe 1.2 não tem mais a API
  legada (`solutions`) nem o modelo "full-range" do spec; a API Tasks só oferece o `blaze_face_short_range`
  (feito para selfie). Comparado no podcast de teste, a 1 quadro/6 s: YuNet achou rosto em 67/85 quadros,
  MediaPipe em 54/85 (perdia perfis e rostos menores no plano aberto). YuNet: ~14 ms/quadro em 960×540 na CPU.
  Modelos em `backend/assets/models/` (YuNet usado; o .tflite do MediaPipe ficou só pela comparação).
  `mediapipe` saiu do requirements.
- **Pré-análise** = job `reframe` no **slot leve** (CPU), enfileirado junto com a transcrição (roda em paralelo
  com o Whisper na GPU). O spec marcava reframe como GPU, mas nada aqui usa GPU. Resultado em `scenes.json`
  (trocas de cena) e `faces.json` (rostos a 5 fps, normalizados ao quadro original, mesmo com fonte ≠ 16:9).
  `Project.faces_ready`. Se o render precisar e a análise não existir, ela é feita na hora.
- **Frames para detecção** decodificados pelo ffmpeg (`fps=5`, pipe bgr24) em vez de OpenCV `VideoCapture`:
  mais rápido e o tempo de cada amostra é exato (i/5).
- **Cenas**: PySceneDetect `ContentDetector(27)`, em blocos de 60 s (progresso + cancelamento). ~39 s para 18 min.
- **Alvo por cena**: rostos agrupados por posição X; o grupo dominante (soma das áreas = maior + mais presente)
  é seguido. Rostos < 3,5% da altura são ignorados. Cena sem rosto → centro.
- **Suavização**: começa na mediana do 1º segundo (sem rampa), zona morta de 8% da largura do crop e
  exponencial α = 0,2 por amostra (o spec sugere ≈ 0,1; a 5 fps isso dava ~2 s de atraso). Troca de cena =
  recomeça sem suavizar (salto seco).
- **Split**: por cena, se ≥ 60% das amostras têm os 2 rostos principais → metade de cima = pessoa da esquerda,
  embaixo = da direita (cada metade 1080×960, rosto a ~42% da altura); senão a cena usa o crop normal.
- **Manual**: `manual_crop_json` = `[{"t": seg_relativo, "x": centro_normalizado}]`, interpolado com smoothstep.
- **Render com crop variável**: ffmpeg decodifica a fonte (`-ss` antes do `-i`, `fps` de saída) → Python
  recorta cada frame → 2º ffmpeg codifica (vídeo cru pelo stdin + áudio da fonte + .ass + loudnorm).
  Sem split, o Python envia o crop no tamanho nativo (ex.: 404×720) e o ffmpeg amplia com lanczos. Com split,
  compõe 1080×1920 no Python. `crop.json` salvo por corte; `GET /clips/{id}/crop-track?fps=` para o editor.
- Fonte já vertical (≤ 9:16) → auto/split viram centro (não há o que reenquadrar).
- Medido no podcast de teste (8,5 min, 720p30, 108 trocas de câmera): pipeline completo em 147 s; render "seguir
  rosto" ~4–5 s por corte de ~22 s, split ~9,5 s. Trilha: maior passo ≤ 0,2% da largura por frame dentro da
  cena; salto exato no frame da troca.

## Fase 6 — Editor
- **Timeline própria (canvas + DOM) em vez do wavesurfer.js.** Precisávamos de janela de contexto ±30 s, faixa de
  miniaturas alinhada, alças com encaixe na palavra (Alt desliga), arrastar o corte inteiro e playhead sem
  re-render — com o wavesurfer isso exigia sincronizar zoom/scroll de dois componentes e lutar com o plugin
  Regions. A forma de onda usa os picos pré-calculados (`waveform.json`, 100/s). Ctrl+roda = zoom, roda = rolar.
- **Preview 9:16 em canvas**: um único `<video>` (o da fonte); o preview desenha o recorte a cada quadro com
  `drawImage` (crop simples, split e fundo borrado), então fica sempre sincronizado. A trilha de auto/split vem de
  `GET /clips/{id}/crop-track` (recalculada quando o corte salvo muda; a anterior fica na tela enquanto carrega).
  Manual é calculado no cliente (smoothstep, igual ao Python) — o retângulo arrastado aparece na hora.
- **Legenda do preview** em HTML/CSS numa camada lógica 1080×1920 escalada, com as MESMAS fontes do render
  (`/api/fonts`, servido de `backend/assets/fonts`). A lógica de linhas/tempos foi portada para TS
  (`lib/captions.ts`) e os dois lados rodam os mesmos casos (`backend/tests/fixtures/captions_cases.json`).
- **Tamanho da fonte**: o "Fontsize" do ASS não é o font-size do CSS e a relação depende da família. Fator MEDIDO
  (altura do "H" no libass ÷ no navegador): Montserrat 0,643, Inter 0,833, Bebas Neue 0,771 (`lib/fonts.ts`).
  Antes da medição o preview ficava 23% maior; depois, preview e quadro do MP4 ficam praticamente idênticos.
  Contorno: `-webkit-text-stroke` com 2× a espessura + `paint-order: stroke fill` (o do ASS fica todo do lado de fora).
- **Ajustes por corte**: o corte aponta para um preset (`caption_style_id`) e guarda ajustes em
  `caption_overrides_json.style`; o render aplica preset + ajustes (`Style.merged`, com validação).
  "Salvar como novo preset" cria um CaptionStyle e zera os ajustes. Escolher um preset zera os ajustes.
- `caption_overrides_json` = `{"words": {...}, "style": {...}, "title_until": 3}` (o formato antigo, só palavras,
  continua sendo lido). Correção de palavra no editor vale só para a legenda daquele corte.
- **Exportar**: `Clip.export_json` = `{"quality": high|normal|small, "normalize_audio": bool}`. Qualidade →
  NVENC cq 19/21/25 (x264 crf 18/20/24) com teto 12/8/4 Mbps.
- **Estado**: Zustand com rascunho + pilha de desfazer (até 200). Edições seguidas do mesmo controle em < 1 s e
  gestos (arrastar alça/slider: `checkpoint()` no início) viram um único passo. **Autosave**: diff do rascunho vs.
  último salvo, PATCH só dos campos alterados, debounce 800 ms; Ctrl+S salva já; renderizar salva antes.
  O rascunho é carregado uma vez por corte (eventos SSE posteriores não sobrescrevem edições em andamento).
- **Atalhos**: Espaço, J (−2 s; o vídeo HTML não toca de trás pra frente de forma confiável), K, L (2× se já
  tocando), ←/→ (1 frame; Shift = 1 s), I/O, Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y também), Ctrl+S, Ctrl+Enter, ? = ajuda.
  Tocar a partir de dentro do corte para no fim dele.
- **Shift+clique** na transcrição: palavra antes do meio do corte vira o início; depois, o fim (com respiro).
- Testes: vitest (25: legendas com casos compartilhados, geometria do crop, encaixe, store/undo/diff) + pytest
  (64, incl. "edição no editor → MP4 final"). Aceite também verificado no navegador com Playwright (Chromium
  headless instalado em `~/.cache/ms-playwright`, só para desenvolvimento).

## Fase 7 — Acabamento
- **Instalação para leigos**: `scripts/setup.sh` faz tudo em 5 etapas. No Linux x86_64, o que faltar é instalado
  SEM sudo em `~/.local` (uv, FFmpeg estático BtbN com libass+NVENC, Node.js 22, Ollama); macOS/outros recebem a
  instrução exata. Depois: venv + deps, `npm ci && build`, `run.py --baixar-modelos` (Whisper conforme o hardware +
  modelo do Ollama; numa máquina sem GPU de 8 GB troca o padrão 7b pelo 3b e grava nas Configurações) e
  `run.py --diagnostico`. `--sem-modelos` pula os ~8 GB de modelos.
- **Aceite verificado de verdade**: (A) cópia limpa do projeto (sem .venv/node_modules/dist/data) → `setup.sh` →
  `start.sh` numa porta separada → projeto real de 8,5 min analisado (estimativa 160 s, real 150 s) e 3 cortes
  renderizados com "seguir rosto"; (B) HOME falso e PATH sem uv/ffmpeg → o setup instalou os dois sozinho e o
  diagnóstico ficou todo verde. Bugs achados e corrigidos no caminho: checagem de libass no shell (o `-filters`
  do FFmpeg 8 tem flags de 2 caracteres) e miniaturas (abaixo).
- **Windows** (`setup.ps1` com winget, `start.bat`) e **macOS** (brew) — scripts escritos mas NÃO testados.
  `requirements.txt` usa marcador para não instalar as libs CUDA no macOS; `run.py` põe as DLLs CUDA no PATH no Windows.
- **Miniaturas**: `fps=1/10` não gerava nada em vídeo < 10 s e o encoder JPEG do FFmpeg 8 recusa YUV "limited
  range" → agora `select` (quadro 0 e depois a cada 10 s) + `out_range=full,format=yuvj420p`.
- **Cache por arquivo** na preparação: cada etapa (áudio, forma de onda, proxy, miniaturas) só roda se o arquivo
  dela faltar; fonte alterada apaga todos os derivados.
- **Armazenamento** (Configurações): uso por pasta + limpeza de (1) temporários/restos (`.part`, `.tmp`, pastas de
  projetos/cortes apagados), (2) `audio.wav` de projetos prontos, (3) proxies de projetos sem uso há N dias
  (atividade = último update do projeto ou de um corte). Recusa limpar com job rodando (apagaria `.tmp` em uso).
  Proxy apagado → projeto/editor mostram **"Preparar de novo"** (job `probe_proxy` com `Project.prepare_only`:
  restaura só os arquivos, sem refazer transcrição/IA).
- **Estimativa de tempo** (`GET /projects/{id}/estimate`): fatores medidos nesta máquina (transcrição large-v3 GPU
  ~6,5× tempo real, preparo ~20× com NVENC, IA ~30 s por janela de 8 min); CPU com fatores conservadores; etapas
  em cache contam 0. Mostrada no diálogo "Configurar análise".
- **Erros amigáveis** centralizados em `app/errors.py` (memória da GPU, CUDA, disco cheio, permissão, arquivo
  sumido, serviço sem resposta); usados na Fila, no projeto e no corte, sempre com o detalhe técnico junto.
- **Presets extras**: Impacto (Bebas Neue 1 palavra, vermelho, pop), Minimal (Inter SemiBold, sem destaque, embaixo),
  Amarelo (texto amarelo, destaque branco). Entram em bancos existentes no próximo start.
- **Corte manual do zero** abre direto no editor. Idioma padrão das Configurações vale para projetos novos.
- `run.py` avisa em PT-BR se a porta já estiver em uso (e sugere `MDC_PORT`). Editor carregado sob demanda
  (bundle principal < 500 kB).
- Configurações completas (§9.6): Whisper (modelo/dispositivo/precisão), Ollama (endereço, modelo instalado, Testar),
  encoder, idioma padrão, pasta de exportação, normalização de áudio, yt-dlp, cookies e armazenamento.

## Templates por tipo de conteúdo (pós-spec)
- `services/templates.py`: Geral, Gameplay, Podcast, Debate. Cada um define enquadramento, preset/posição da
  legenda, prompt extra da IA, pista de volume e pesos da nota. Escolhido em "Configurar análise" (vira o padrão
  do projeto) e em **"Renderizar todos"** (`POST /projects/{id}/apply-template`, com `render: true`), que
  aplica a todos os cortes ativos preservando correções de palavras/títulos. Corte manual herda o template.
- **Gameplay** (`reframe_mode="gameplay"`): webcam em cima (40% da altura, ajustável 25–60%), jogo centralizado
  embaixo. A facecam é detectada como o rosto que fica parado no mesmo lugar em ≥ 25% do vídeo (overlay fixo).
  Sem facecam estável → jogo inteiro sobre fundo borrado. No editor dá para arrastar a webcam e o jogo, mudar o
  zoom e a altura (`Clip.layout_json`). Render só com filtros do ffmpeg (crop + vstack), sem pipe pelo Python.
  IA: prompt de jogadas decisivas/reações; falas com pico de volume ≥ 1,6× a média chegam marcadas
  "[VOLUME ALTO]"; nota = 0,6 IA + 0,4 heurística de reações (picos de volume), em vez de ritmo de fala.
  Legenda na divisa webcam/jogo (y = 0,4).
- **Podcast** (`reframe_mode="speaker"`): quem está falando no centro, troca com corte seco (mín. 1,5 s
  no quadro; a outra pessoa precisa estar claramente à frente por 0,8 s; só troca durante fala).
  Quem fala = **abertura dos lábios** (FaceLandmarker do MediaPipe, pontos 13/14 ÷ 78/308), desvio em ~1 s:
  medido no podcast de teste, a distribuição é bimodal (calado ≤ 0,02; falando 0,03–0,2). Pessoa de perfil
  (lábios ilegíveis) entra por exclusão: há voz e quem é legível está calado → fala quem não dá para ler.
  Último recurso (ninguém legível): diff de imagem da boca descontando olhos/região em volta, normalizado.
  Tentativas que NÃO funcionaram (registradas para não repetir): só diff de imagem (mãos gesticulando perto da
  boca enganam — 2 de 8 errados) e diarização por MFCC + k-means (pureza 56% ≈ acaso).
  Verificação visual em 11 momentos de plano aberto do podcast de teste: todos plausivelmente corretos.
  Custo: análise de rostos ~10 s por minuto de vídeo (era ~5,5), em paralelo com a transcrição.
  `faces.json` v5 = [cx, cy, w, h, score, atividade_boca, frontalidade, abertura_lábios]; versões antigas são
  refeitas automaticamente. `mediapipe` voltou ao requirements só por isso.
- **Debate**: tela dividida existente (esquerda em cima, direita embaixo) + legenda no meio (y = 0,5) + prompt de
  confrontos/réplicas.

## Redesign da UI (2026-11-24)

- **Identidade**: base grafite neutra (não tinge a percepção de cor do vídeo) + um único acento, o amarelo-legenda `#FFD23F` (vem das legendas de shorts). Coral `#FF5A4E` só para destrutivo/erro. Tokens em `frontend/src/index.css`.
- **Tipografia**: Archivo variável (`@fontsource-variable/archivo`, empacotada — app é offline). Títulos com a utility `font-display` (largura 118%, peso 800).
- **Tela Início** (`/inicio`, nova rota padrão): um campo único "cole o link → Criar cortes" que baixa com `send_to_project=true` (download → projeto → análise sozinhos); playlists vão para Downloads com `?links=` e são analisadas automaticamente; arrastar/escolher arquivo faz upload e abre o projeto. Mostra "Em andamento", "Continuar editando" e "Como funciona".
- **Sidebar** na ordem do fluxo, com o job que está rodando visível (progresso) e recolhida para ícones dentro do editor.
- **Assets** em `frontend/public/brand/` (logo SVG, ilustrações, vídeo-loop do hero) gerados com Higgsfield (gpt_image_2_6 / seedance_2_5). O hero respeita `prefers-reduced-motion`.

## Pacote para postar (roadmap #9, 2026-11-25)

- **Job `post_pack`** (por corte, `ref_id` = clip; slot de GPU porque usa o Ollama). Opções em `Job.params_json`
  (`{"texts": bool, "cover": bool}`, coluna nova). Resultado em `Clip.post_json`: `tiktok {caption, hashtags}`,
  `reels {caption, hashtags}`, `shorts {title, description, hashtags}` + `cover_t`, `cover_at`, `model`.
  Gerar/editar o pacote **não** muda o status do corte (o MP4 continua válido). Editar texto = `PUT /clips/{id}/post`.
- **Textos**: o mesmo modelo da análise (qwen2.5:7b), com JSON schema próprio (`ollama_chat(schema=...)`); 1 retentativa
  com temperatura menor se o JSON vier inválido. Normalização no backend: limites (TikTok 300, Reels 600, título do
  Shorts 100), hashtags sem acento/espaço/repetidas (TikTok 5, Reels 8, Shorts 3 + `#Shorts` fixa no texto final).
  Medido no projeto GTA (10 cortes): ~20 s por corte com a capa. O 7B às vezes inventa hashtag (ex.: "clonadore") —
  por isso tudo é editável no app.
- **Capa**: reaproveita o plano de render (`render_plan`, extraído do `handle_render`): o quadro sai com o mesmo
  enquadramento do MP4, mas sem legenda. Para os modos que seguem rosto, usa `reframer.frame_crop`; para os modos
  só com filtros (centro, borrado, gameplay), usa o `video_filter` sem o `.ass`. 8 candidatos (1 por faixa do corte, longe de trocas de cena), cada
  um com nota de rosto pelo `faces.json` (tamanho × confiança × de frente, penaliza boca escancarada, só rostos dentro
  do crop) e nitidez (variância do Laplaciano); nota = 0,65 rosto + 0,35 nitidez (sem rostos: só nitidez).
  `cover-titulo.jpg` = mesma imagem + título (ASS próprio, 120 px, terço de baixo).
- **Exportar**: `GET /projects/{id}/export.zip` monta o zip na hora em `data/tmp/` (MP4/JPG sem compressão → 600 MB
  em ~3 s) e apaga depois de enviar. Só entram cortes ativos com MP4; `textos.txt` avisa quantos ficaram de fora.
  `textos.csv` tem BOM UTF-8 para o Excel abrir os acentos certo.


