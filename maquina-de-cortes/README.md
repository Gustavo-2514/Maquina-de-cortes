# Máquina de Cortes ✂️

Transforma vídeos longos (podcasts, lives, aulas) em **cortes verticais prontos para TikTok, Reels e Shorts** — tudo no seu computador, sem pagar nada e sem mandar seus vídeos para a internet.

O que ela faz:

1. **Baixa** vídeos por link (YouTube, Twitch, TikTok, Instagram, X…).
2. **Transcreve** a fala, palavra por palavra.
3. Uma **IA local** escolhe os melhores trechos e dá uma nota de "potencial viral".
4. **Enquadra em 9:16** seguindo o rosto de quem aparece (ou divide a tela entre duas pessoas).
5. Coloca **legendas animadas** no estilo que você escolher.
6. Você **ajusta** cada corte num editor e **exporta** o MP4 final.

---

## Do que você precisa

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Linux (Ubuntu 22.04 ou mais novo) | Ubuntu 24.04+ |
| Placa de vídeo | nenhuma (funciona só na CPU, mas é lento) | NVIDIA com 8 GB (ex.: RTX 3050/3060) |
| Espaço livre | 20 GB | 50 GB ou mais |
| Internet | só para instalar e para baixar vídeos | |

> **Windows e macOS:** existem scripts (veja [mais abaixo](#windows-e-macos)), mas este guia foi testado no Linux.

> **Tem placa NVIDIA?** Instale o driver da NVIDIA **antes** de começar. No Ubuntu: abra **Programas e Atualizações → Drivers adicionais**, escolha o driver "nvidia-driver" recomendado, aplique e reinicie o computador.

---

## Instalação (uma vez só)

### 1. Abra o Terminal na pasta do programa

- Abra o **Terminal** (no Ubuntu: `Ctrl` + `Alt` + `T`).
- Digite `cd ` (com um espaço no final), **arraste a pasta `maquina-de-cortes` para dentro da janela do Terminal** e aperte `Enter`.

### 2. Rode o instalador

Copie, cole no Terminal (`Ctrl` + `Shift` + `V`) e aperte `Enter`:

```bash
scripts/setup.sh
```

Ele faz tudo sozinho e mostra o andamento em 5 etapas:

1. **Ferramentas** — instala o que faltar (Python, FFmpeg, Node.js e Ollama), **sem pedir senha**, só dentro da sua pasta pessoal.
2. **Ambiente Python** — bibliotecas do programa.
3. **Interface** — prepara as telas.
4. **Modelos de IA** — baixa o modelo de transcrição e o de IA certos para o seu computador (**~8 GB**, só na primeira vez).
5. **Diagnóstico** — confere se está tudo certo. No final deve aparecer **"Tudo pronto!"**.

⏱️ Leva de **10 a 40 minutos**, dependendo da sua internet. Pode deixar rodando.

> Internet lenta? Use `scripts/setup.sh --sem-modelos` para instalar sem os modelos. Eles baixam sozinhos no primeiro uso.

### 3. Abra o programa

```bash
scripts/start.sh
```

O navegador abre sozinho em **http://localhost:8000**. Se não abrir, digite esse endereço no navegador.

Para **fechar**, volte ao Terminal e aperte `Ctrl` + `C`. Para abrir de novo outro dia, repita o passo 1 (`cd` na pasta) e o passo 3.

---

## Seu primeiro corte

1. **Downloads** → cole o link do vídeo → **Analisar** → escolha a qualidade → **Baixar**.
2. Quando terminar, clique em **Criar cortes**.
3. Na janela **Configurar análise**, escolha quantos cortes quer, a duração e o estilo de legenda. O app mostra o **tempo estimado**. Clique em **Analisar**.
4. Acompanhe o progresso: preparar o vídeo → transcrever → a IA escolhe os trechos.
5. Aparece a lista de **Cortes sugeridos**, do melhor para o pior. Clique em um para assistir ao trecho.
6. **Editar** abre o editor, onde você ajusta o início e o fim, a legenda, o enquadramento e o título.
7. **Renderizar** (ou **Renderizar todos**) gera os MP4. Depois é só **Baixar** ou **Abrir pasta**.

> Também dá para usar um vídeo que já está no computador: **Projetos → Novo projeto → Enviar arquivo** (ou **Caminho local**, que não copia o arquivo).
>
> Para criar um corte do zero, use **Novo corte manual** na página do projeto.

### Atalhos do editor

| Tecla | O que faz |
|---|---|
| `Espaço` | tocar / pausar |
| `←` / `→` | anda 1 quadro (com `Shift`: 1 segundo) |
| `I` / `O` | marca o início / o fim do corte onde o vídeo está |
| `J` / `K` / `L` | volta 2 s / pausa / toca (aperte `L` de novo para 2×) |
| `Ctrl+Z` / `Ctrl+Shift+Z` | desfazer / refazer |
| `Ctrl+S` | salvar agora (ele também salva sozinho) |
| `Ctrl+Enter` | renderizar |
| `?` | mostra os atalhos |

Na transcrição: **clique** numa palavra para ir até ela, **Shift+clique** para marcar início/fim e **duplo clique** para corrigir a legenda.

### Templates: escolha pelo tipo de vídeo

Ao configurar a análise (e de novo em **Renderizar todos**), escolha o template:

| Template | Como fica o corte | O que a IA procura |
|---|---|---|
| **Gameplay** | webcam do streamer em cima, jogo centralizado embaixo | jogadas decisivas e reações fortes (gritos, risadas) |
| **Podcast** | quem está falando fica no centro, com corte seco na troca | opiniões fortes, histórias, frases de impacto |
| **Debate** | tela dividida: uma pessoa em cima, a outra embaixo | confrontos, réplicas, discordâncias |
| **Geral** | segue o rosto principal | os melhores momentos em geral |

No editor (aba **Enquadrar**) dá para ajustar cada corte. Na gameplay você arrasta a webcam e o jogo e muda o tamanho de cada um.

### Qual enquadramento usar?

- **Seguir rosto**: o padrão. Acompanha quem aparece e corta seco quando a câmera muda.
- **Quem fala no centro**: lê os lábios e mostra quem está falando (podcast/entrevista).
- **Webcam + jogo**: gameplay com facecam.
- **Tela dividida**: duas pessoas na mesma cena (podcast). A pessoa da esquerda fica em cima e a da direita embaixo.
- **Inteiro + fundo borrado**: telas, jogos e slides, onde não dá para cortar as laterais.
- **Centro** e **Manual**: quando você quer controlar o enquadramento.

---

## Quando algo dá errado

O primeiro lugar para olhar é **Configurações → Diagnóstico**. Ele mostra ✅ ou ❌ para cada peça e diz como resolver.

| Problema | Solução |
|---|---|
| Download do YouTube falha | **Configurações → Atualizar yt-dlp** e depois feche e abra o app |
| "O site pediu login" / restrição de idade | exporte um `cookies.txt` do navegador (extensão "Get cookies.txt LOCALLY") e informe o caminho em **Configurações** |
| "A placa de vídeo ficou sem memória" | feche jogos/outros programas pesados ou escolha um modelo Whisper menor em **Configurações** |
| "O Ollama não está respondendo" | feche e abra o app (ele liga o Ollama sozinho); em **Configurações**, use **Testar** |
| Muito lento | sem placa NVIDIA tudo roda na CPU; em **Configurações**, use o Whisper `small` ou `base` |
| "Porta 8000 em uso" | rode `MDC_PORT=8001 scripts/start.sh` e abra http://localhost:8001 |
| Disco cheio | **Configurações → Armazenamento → Liberar** |

Cada tarefa com erro aparece na **Fila** com a explicação, e em **Detalhe técnico** está a mensagem completa, útil para pedir ajuda. Os registros ficam em `data/logs/`.

---

## Onde ficam os arquivos

Tudo fica dentro da pasta `data/`:

| Pasta | Conteúdo |
|---|---|
| `data/downloads/` | vídeos baixados |
| `data/projects/` | arquivos de trabalho de cada projeto (pode limpar em **Configurações → Armazenamento**) |
| `data/exports/` | **os cortes prontos (MP4)** — ou a pasta que você escolher em **Configurações** |
| `data/logs/` | registros para diagnóstico |

## Atualizar ou desinstalar

- **Atualizar:** substitua a pasta pela versão nova (mantenha a sua pasta `data/`) e rode `scripts/setup.sh` de novo.
- **Desinstalar:** apague a pasta `maquina-de-cortes`. Para remover também as ferramentas e os modelos, apague `~/.local/opt/` (FFmpeg, Node e Ollama instalados pelo setup), `~/.ollama/models` (modelo de IA) e `~/.cache/huggingface` (Whisper).

---

## Windows e macOS

**Não testados.** O desenvolvimento foi feito no Ubuntu.

- **Windows** (PowerShell): `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`, depois `scripts\start.bat`. O script instala as ferramentas com o `winget`.
- **macOS**: instale antes `brew install ffmpeg node` e o Ollama (https://ollama.com/download). Depois rode `scripts/setup.sh` e `scripts/start.sh`. No Mac não há NVIDIA, então tudo roda na CPU.

---

## Para desenvolvedores

- Especificação: `../MAQUINA_DE_CORTES.md`. Decisões de implementação e medições: `DECISIONS.md`.
- Backend: FastAPI + SQLite + worker próprio (`backend/app`). Frontend: React + Vite + Tailwind (`frontend/src`).
- Modo desenvolvimento, com recarga automática: `.venv/bin/python run.py --dev` (interface em http://localhost:5173).
- Testes: `cd backend && ../.venv/bin/pytest` e `cd frontend && npm test`.
- Utilitários: `.venv/bin/python run.py --diagnostico` e `run.py --baixar-modelos`.

## Uso responsável

Baixe e corte apenas conteúdo que você tem direito de usar: seu, com licença ou com permissão do criador. Algumas plataformas só monetizam cortes de terceiros com autorização.
