# AI Studio

Ferramentas locais de automação de conteúdo com IA.

| Módulo | O que é | Status |
|---|---|---|
| [`maquina-de-cortes/`](maquina-de-cortes/) | Transforma vídeos longos em cortes verticais (9:16) com legendas animadas — tudo local. Guia de instalação e uso no [README do módulo](maquina-de-cortes/README.md). | Fases 0–7 da spec concluídas + templates por tipo de conteúdo + redesign da UI |

- Especificação: [`MAQUINA_DE_CORTES.md`](MAQUINA_DE_CORTES.md)
- Decisões técnicas: [`maquina-de-cortes/DECISIONS.md`](maquina-de-cortes/DECISIONS.md)

---

## Roadmap — features e melhorias (2026-11-24)

Ordem recomendada para começar: **1 → 4 → 6 → 9** (rede de segurança → nota que faz sentido + remoção de silêncios, que melhoram todo corte → pacote de exportação, que mais economiza tempo).

### Higiene
1. **Controle de versão** — repositório git (feito neste commit).
2. **Rotação de logs** — `data/logs/api.log` cresce sem limite (ex.: rotação 5 MB × 3).
3. **Windows/macOS** — scripts escritos mas nunca testados; testar ou marcar como "experimental" no README.

### Qualidade dos cortes
4. **Notas comprimidas** — o qwen2.5:7b dá quase tudo entre 80–89. Normalizar por ranking dentro do projeto ou pedir comparação par a par dos candidatos, para a nota separar o bom do mediano.
5. **Aprender com o seu gosto** — 👍/👎 por corte (e o que é exportado/descartado) vira exemplos no prompt e ajusta os pesos de cada template. Tudo local.
6. **Remover silêncios e "éé/hum"** (jump cuts) — os timestamps por palavra do Whisper já existem; falta cortar no render.
7. **Zoom punch-in nas palavras de ênfase** — marcadas pela IA ou por pico de volume; zoom de 1,1–1,15× curto, usando o pipeline de crop por frame.
8. **Gancho no início** — a IA sugere um trecho forte do próprio corte para abrir (cold open) ou um texto-gancho nos primeiros 2 s.

### Produtividade
9. ✅ **Pacote para postar** (feito em 2026-11-25) — título, descrição e hashtags por plataforma gerados pela IA + capa automática (quadro com rosto e nitidez); "Exportar tudo" em `.zip` com os MP4 e um `.csv`/`.txt` com os textos. (Sem postar automaticamente — continua fora do escopo.)
10. **Formatos além de 9:16** — 1:1 e 4:5 (feed) e 16:9 (YouTube).
11. **Pasta monitorada** — vídeo que cai em uma pasta vira projeto → análise → render sozinho.
12. **Busca em todas as transcrições** — "todos os momentos em que falaram de X", abrindo o editor no ponto (SQLite FTS5, sem dependência nova).

### Visual e legendas
13. **Emojis automáticos** por palavra-chave na legenda (preset opcional) — o "B-roll leve" da v2.
14. **Barra de progresso/retenção** e **marca d'água/logo** por projeto.
15. **Trilha de fundo com ducking automático** sob a fala (sidechain no FFmpeg) + biblioteca local de músicas.
16. **Tradução da legenda** via Ollama (bilíngue: original em cima, tradução embaixo).

### Infra
17. **Modelo de IA maior opcional** para a análise quando houver VRAM/tempo (ex.: fila noturna).
18. **App desktop** (Tauri/PyInstaller) para quem não usa terminal.

---

## Ideias com Claude + Higgsfield (MCP) — 2026-11-25

> **Princípio:** a spec diz "100% local". Tudo abaixo é **opcional** ("modo nuvem"), desligado por padrão, com o caminho local (Ollama/FFmpeg) continuando como fallback. Toda ação que gasta crédito mostra o custo antes (`estimate_*_cost` / `balance` do Higgsfield) e pede confirmação.

### Dois jeitos de integrar
- **A) Claude Code como operador (recomendado para começar)** — uma *skill* no repositório (ex.: `/cortes`) em que o Claude Code usa a API REST local (`localhost:8000`) e as ferramentas do MCP do Higgsfield da sua própria sessão. Zero mudança no backend, nenhuma chave guardada no app.
- **B) Dentro do app** — provedor "Claude" opcional no backend (Anthropic API, chave nas Configurações), com o mesmo schema JSON que o Ollama já usa. Para chamar o Higgsfield de dentro do app seria preciso o conector MCP da API + token do Higgsfield — mais trabalho; deixar para depois que o caminho A provar valor.

### Com Claude
19. ✅ (2026-11-25) **Claude como provedor de análise** — alternativa ao qwen2.5:7b no `highlighter` (mesmo schema). Resolve boa parte do item 4: um modelo maior separa melhor o bom do mediano, especialmente pedindo **comparação par a par** dos candidatos. Haiku para o pacote de postagem (barato), Sonnet/Opus para escolher os cortes.
20. ✅ (2026-11-25) **Revisão visual do corte (QA)** — Claude recebe ~8 quadros do render + a transcrição e devolve um checklist: rosto cortado pelo crop? legenda tampando algo? começo fraco? termina no meio da frase? Vira um selo ✅/⚠️ no `ClipsPanel` antes de exportar.
21. **Gancho e títulos melhores** (item 8 + pacote) — Claude escolhe o cold open dentro do corte e escreve o texto-gancho dos 2 primeiros segundos, com variações A/B por plataforma.
22. ✅ (2026-11-25, em `.claude/skills/cortes/`) **Skill `/cortes <url ou arquivo>`** — orquestra o fluxo todo: baixa → cria projeto → espera a análise → revisa os candidatos → renderiza os aprovados → monta o pacote para postar → te mostra o resumo. Um subagente "editor-chefe" pode filtrar os cortes antes de você ver.
23. **Guia de estilo do canal** (item 5) — Claude resume seus 👍/👎 e o que foi exportado/descartado num guia curto ("prefere histórias pessoais, evita trechos técnicos…") que entra no prompt — inclusive no do Ollama, então o aprendizado continua valendo no modo local.
24. **Tradução de legenda de alta qualidade** (item 16) — Claude traduz mantendo gírias e o timing por palavra; útil para a legenda bilíngue e para o item 32.

### Com o Higgsfield (MCP)
25. ✅ (2026-11-25, como passo da skill `/cortes`; ainda não na UI) **Capa/thumbnail com IA** — parte do quadro escolhido pelo pacote para postar: `remove_background` no rosto + fundo gerado (`generate_image`) + título grande, e `upscale_image` no final. Hoje isso está sendo feito à mão (ex.: `roubar-para-vender-com-titulo.jpg`); vira um botão "Gerar capa" com 3 variações.
26. **Reenquadramento inteligente para outros formatos** (item 10) — `reframe` para 9:16 quando o crop por rosto falha (duas pessoas longe, slides, tela compartilhada) e `outpaint_image`/`reframe` para preencher 4:5 e 1:1 em vez de barras pretas.
27. **B-roll gerado** — Claude marca trechos sem rosto ou com ideia abstrata ("imagina uma cidade em 2050") e escreve o prompt; o Higgsfield gera 3–4 s de vídeo (`generate_video`) que o render insere como cutaway/overlay. Evolução do "B-roll leve" (item 13).
28. **Efeitos sonoros nos pontos de ênfase** — `search_sound_effects`/`download_sound_effect` para whoosh/pop sincronizado com o zoom punch-in (item 7) e as palavras destacadas; biblioteca salva localmente depois do primeiro download.
29. **Música de fundo** (item 15) — `tiktok_music_trending` para sugerir trilhas em alta por tema do corte; o ducking continua no FFmpeg. (Atenção a licença: usar só como sugestão para escolher na plataforma, ou faixas livres.)
30. **Áudio limpo** — `separate_stems` para isolar a voz de fontes com ruído ou com música protegida por direitos autorais antes de transcrever e renderizar (melhora também a precisão do Whisper).
31. **Upscale de fonte fraca** — `upscale_video` para vídeos 480p/720p antes do crop 9:16 (o crop amplia muito e fica borrado). Só nos trechos dos cortes aprovados, para economizar crédito.
32. **Dublagem do corte** — legenda traduzida pelo Claude (item 24) + voz (`create_voice`/`generate_audio`, ou `voice_change`) para publicar o mesmo corte em outro idioma. Só com a voz do próprio criador e com consentimento dele.
33. **Segunda opinião de viralidade** — `virality_predictor` (ou `video_analysis_create`) nos cortes renderizados, mostrado ao lado da nota local; com o tempo dá para medir qual das duas acerta mais e calibrar os pesos dos templates.
34. **Identidade visual do projeto** (item 14) — logo e paleta salvos como `elements` no Higgsfield; intro/outro animada de 1–2 s gerada uma vez e reaproveitada em todos os cortes.

### Fora do escopo (de propósito)
- Postar automaticamente (`tiktok_prepare_publish` etc.) — continua fora, como no item 9.
- Avatares/influencers sintéticos falando como se fossem o criador.

### Ordem sugerida
**22 → 25 → 19 → 20**: a skill `/cortes` não exige mexer no backend e já permite testar capa com IA e a análise com Claude na prática; só depois vale levar o que funcionar para dentro do app (caminho B). Depois, **26 e 31** (atacam os cortes que hoje saem ruins) e **27/28** (deixam o corte com cara de editado).
