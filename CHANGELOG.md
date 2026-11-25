# Changelog

Todas as mudanças importantes deste projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Guia de contribuição (`CONTRIBUTING.md`), padrão de commits Conventional Commits com validação por hook
  (`.githooks/commit-msg`), modelo de mensagem (`.gitmessage`) e modelo de pull request.

## [0.1.0] - 2026-11-25

Primeira versão pública da **Máquina de Cortes**.

### Adicionado

- **Downloads** por link (YouTube, Twitch, TikTok, Instagram, X e outros, via yt-dlp): fila, progresso em tempo real,
  cancelar, retomar depois de reiniciar, playlists, escolha de qualidade e áudio em MP3.
- **Projetos** a partir de download, envio de arquivo ou caminho local.
- **Transcrição** palavra por palavra com Whisper (faster-whisper), na placa NVIDIA ou no processador, com correção
  manual de palavras.
- **Análise com IA local** (Ollama + Qwen 2.5): escolhe os melhores trechos, dá nota de potencial viral e explica o
  motivo. Duração mínima e máxima por corte (padrão 60–90 s) e instruções extras para a IA.
- **Estimativa de tempo** da análise antes de começar, de acordo com o hardware.
- **Enquadramento 9:16**: seguir rosto (YuNet), quem fala no centro (leitura dos lábios com MediaPipe), webcam + jogo,
  tela dividida, inteiro com fundo borrado, centro e manual, com detecção de troca de câmera (PySceneDetect).
- **Templates por tipo de vídeo**: Geral, Gameplay, Podcast e Debate.
- **Legendas animadas** em 7 estilos (Hormozi, Clean, Neon, Karaokê, Impacto, Minimal e Amarelo), ajustáveis por corte.
- **Editor** com prévia vertical, linha do tempo com forma de onda, transcrição clicável, desfazer/refazer,
  salvamento automático e atalhos de teclado.
- **Render** com NVENC (ou x264), áudio normalizado para −14 LUFS e "Renderizar todos".
- **Pacote para postar**: título, legenda e hashtags para TikTok, Reels e Shorts, capa automática e
  "Exportar tudo (.zip)" com MP4, capas, `textos.csv` e `textos.txt`.
- **IA paga opcional** por chave de API (Claude, OpenRouter, OpenAI, Gemini, DeepSeek, xAI, Groq, Mistral ou qualquer
  API compatível com a OpenAI) para a análise e para a **revisão visual** dos cortes, sempre com custo estimado antes e
  custo real depois.
- **Configurações** com diagnóstico do sistema, escolha de modelos, armazenamento (limpeza de temporários),
  atualização do yt-dlp e `cookies.txt`.
- **Instaladores** sem sudo para Linux (`scripts/setup.sh`), além de Windows (`setup.ps1`) e macOS (não testados).
- **`scripts/sugerir-modelos`**: sugere os modelos de transcrição e de IA ideais para o computador de cada pessoa e,
  com `--aplicar`, já configura o app e baixa o modelo.
- README completo com passo a passo para iniciantes, prints das telas e explicação dos modelos.
- Licença MIT.

[Não lançado]: https://github.com/Gustavo-2514/ai-studio/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Gustavo-2514/ai-studio/releases/tag/v0.1.0
