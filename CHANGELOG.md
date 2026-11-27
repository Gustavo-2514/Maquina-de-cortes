# Changelog

**Português** · [English](CHANGELOG.en.md)

Todas as mudanças importantes deste projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o projeto usa [versionamento semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Corrigido

- **Tentar de novo** após erro na análise da IA agora retoma do trecho que falhou: as respostas dos trechos já
  lidos ficam guardadas no projeto e são reaproveitadas (mesmo modelo e mesmas opções). Ao concluir a análise o
  cache é apagado, então **Reanalisar** continua pedindo sugestões novas.
- O Ollama passa a ter um teto de 2048 tokens por resposta; antes, um modelo que entrava em loop gerava centenas
  de KB de texto e a análise falhava com "O LLM não devolveu um JSON válido".
- Vídeos com fala muito densa (debates, podcasts com muita gente) falhavam sempre no mesmo trecho: o pedido
  passava do contexto de 8192 tokens, o Ollama cortava o começo (as instruções) em silêncio e o modelo devolvia
  lixo. Agora o tamanho do pedido é estimado antes de enviar e, só quando não cabe, o contexto é aumentado até o
  máximo do modelo instalado (lido do Ollama); se nem assim couber, o trecho é dividido em dois.
- **Tela dividida (Debate)** decide momento a momento: com duas pessoas no quadro divide (esquerda em cima,
  direita embaixo); quando só uma aparece, ela ocupa a tela inteira, centralizada. Antes a decisão valia para a
  cena toda e a mesma pessoa podia aparecer em cima e embaixo (o mesmo rosto casava com os dois lados); agora só
  divide com dois rostos diferentes, sem sobreposição e afastados na horizontal. Trechos com menos de 1 s são
  absorvidos pelo vizinho, então uma falha rápida de detecção não faz a tela piscar.

## [1.0.0] - 2026-11-26

### Adicionado

- Guia de contribuição (`CONTRIBUTING.md`), padrão de commits Conventional Commits com validação por hook
  (`.githooks/commit-msg`), modelo de mensagem (`.gitmessage`) e modelo de pull request.
- Versões em inglês de todos os documentos Markdown (`*.en.md`).
- Escolha da qualidade do download (melhor, 1080p ou 720p) direto no Início, antes de colar o link.
  A última escolha fica salva e vale também na tela de Downloads.
- Renderização como etapa do pipeline: ao clicar em **Criar cortes** no Início, uma janela pergunta o tipo de
  vídeo (Geral, Gameplay, Podcast, Debate) e se já deve renderizar os cortes. Com a opção marcada, o projeto segue
  sozinho até os MP4 finais (etapa "Renderizar cortes") e só fica "Pronto" quando o último render termina.
  A mesma opção existe na configuração da análise e na tela de Downloads.

### Alterado

- Novo design system minimalista (`maquina-de-cortes/docs/DESIGN_SYSTEM.md`): três cores (preto `#000000`,
  branco `#ffffff` e vermelho `#df2531` só para destaques), fonte Poppins, sem sombras e ilustrações em escala de cinza.
  Logo e favicon redesenhados na nova paleta.
- Acabamento de interface seguindo as Web Interface Guidelines da Vercel: link "Pular para o conteúdo", microinterações
  em botões, cards e links, entrada única do hero, pausa no vídeo de fundo, mensagens de erro que dizem o que fazer
  e barra lateral só com ícones em telas estreitas.
- Os cards de template (Geral, Gameplay, Podcast e Debate) nas janelas "Configurar análise" e "Renderizar todos"
  agora têm capas ilustradas que mostram o vídeo original virando o corte vertical.

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

[Não lançado]: https://github.com/Gustavo-2514/ai-studio/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Gustavo-2514/ai-studio/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/Gustavo-2514/ai-studio/releases/tag/v0.1.0
