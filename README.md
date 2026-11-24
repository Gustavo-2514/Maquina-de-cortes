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
9. **Pacote para postar** — título, descrição e hashtags por plataforma gerados pela IA + capa automática (quadro com rosto e nitidez); "Exportar tudo" em `.zip` com os MP4 e um `.csv`/`.txt` com os textos. (Sem postar automaticamente — continua fora do escopo.)
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
