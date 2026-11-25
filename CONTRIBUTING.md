# Como contribuir

**Português** · [English](CONTRIBUTING.en.md)

Obrigado pelo interesse em melhorar a **Máquina de Cortes**! Este guia explica como reportar problemas, sugerir ideias e
enviar código.

## Sumário

- [Formas de contribuir](#formas-de-contribuir)
- [Reportar um problema](#reportar-um-problema)
- [Preparar o ambiente](#preparar-o-ambiente)
- [Fluxo de trabalho](#fluxo-de-trabalho)
- [Padrão de commits (Conventional Commits)](#padrão-de-commits-conventional-commits)
- [Pull requests](#pull-requests)
- [Estilo de código](#estilo-de-código)
- [O que não enviar](#o-que-não-enviar)

## Formas de contribuir

- **Testar no Windows ou no macOS**: os scripts existem, mas quase não foram testados. Relatos ajudam muito.
- **Reportar bugs** e **sugerir funções** pelas *issues*.
- **Melhorar a documentação**: se algo no README não ficou claro para você, provavelmente não está claro para outros.
- **Enviar código**: correções, novas funções, testes.

Para mudanças grandes (nova função, troca de biblioteca, mudança de arquitetura), **abra uma issue antes** para
conversarmos. Assim ninguém perde tempo com algo que não vai entrar.

## Reportar um problema

Abra uma *issue* com:

1. **O que aconteceu** e **o que você esperava**.
2. **Passos para reproduzir.**
3. **Seu ambiente**: sistema (ex.: Ubuntu 24.04, Windows 11), placa de vídeo e memória RAM.
4. A saída do diagnóstico: `.venv/bin/python run.py --diagnostico` (dentro de `maquina-de-cortes`).
5. O **Detalhe técnico** do erro (na tela **Fila**) ou o trecho relevante de `data/logs/`.

> Não cole chaves de API, cookies nem caminhos com dados pessoais.

## Preparar o ambiente

```bash
git clone https://github.com/Gustavo-2514/ai-studio.git
cd ai-studio

# Ativa a validação das mensagens de commit e o modelo de mensagem (uma vez por clone)
git config core.hooksPath .githooks
git config commit.template .gitmessage

cd maquina-de-cortes
scripts/setup.sh                       # instala tudo
.venv/bin/python run.py --dev          # API em :8000 e interface com recarga automática em :5173
```

Estrutura principal:

| Pasta | Conteúdo |
|---|---|
| `maquina-de-cortes/backend/app/api/` | rotas HTTP (FastAPI) |
| `maquina-de-cortes/backend/app/services/` | transcrição, IA, enquadramento, render, legendas… |
| `maquina-de-cortes/backend/app/worker/` | fila de tarefas |
| `maquina-de-cortes/backend/tests/` | testes do backend (pytest) |
| `maquina-de-cortes/frontend/src/` | interface (React + TypeScript + Tailwind) |
| `maquina-de-cortes/scripts/` | instaladores e utilitários |

Decisões de implementação e medições ficam em [`maquina-de-cortes/DECISIONS.md`](maquina-de-cortes/DECISIONS.md).
Se a sua mudança envolver uma escolha não óbvia, registre lá também.

### Rodar os testes

```bash
cd maquina-de-cortes/backend && ../.venv/bin/pytest
cd maquina-de-cortes/frontend && npm test && npx tsc -b
```

## Fluxo de trabalho

1. Faça um **fork** do repositório e crie uma branch a partir do `main`:
   ```bash
   git checkout -b feat/timeline-zoom
   ```
   Nomes de branch: `<tipo>/<descricao-curta>`, por exemplo `fix/nvenc-fallback`, `docs/windows-setup`.
2. Faça commits pequenos e focados, seguindo o [padrão de commits](#padrão-de-commits-conventional-commits).
3. Rode os testes.
4. Atualize o README e o [`CHANGELOG.md`](CHANGELOG.md) (seção **Não lançado**) se a mudança aparece para quem usa.
5. Abra o **pull request** para o `main`.

## Padrão de commits (Conventional Commits)

Todos os commits seguem o [Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/) e são **escritos em
inglês**.

```text
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Regras

- **type** obrigatório, em minúsculas (tabela abaixo).
- **scope** opcional, entre parênteses: a parte do projeto afetada.
- **description** em inglês, no **imperativo** ("add", não "added" nem "adds"), começando com letra minúscula,
  **sem ponto final**.
- A primeira linha tem no máximo **72 caracteres**.
- O corpo (opcional) explica **o quê** e **por quê**, não o como. Quebre as linhas em 72 caracteres.
- **Mudanças que quebram compatibilidade**: `!` depois do tipo/escopo e um rodapé `BREAKING CHANGE: ...`.
- Referencie issues no rodapé: `Closes #42`.

### Tipos

| Tipo | Quando usar | Entra no CHANGELOG como |
|---|---|---|
| `feat` | nova função para quem usa | Adicionado |
| `fix` | correção de bug | Corrigido |
| `docs` | só documentação | — |
| `style` | formatação, sem mudar comportamento | — |
| `refactor` | reorganização de código, sem mudar comportamento | — |
| `perf` | melhoria de desempenho | Alterado |
| `test` | testes novos ou corrigidos | — |
| `build` | dependências, empacotamento, scripts de instalação | Alterado (se afetar quem usa) |
| `ci` | integração contínua | — |
| `chore` | manutenção que não se encaixa acima | — |
| `revert` | desfaz um commit anterior | — |

### Escopos sugeridos

`ui`, `editor`, `api`, `worker`, `transcriber`, `highlighter`, `reframer`, `render`, `captions`, `downloads`,
`postpack`, `ai`, `scripts`, `deps`.

### Exemplos

```text
feat(editor): add zoom controls to the timeline
fix(render): fall back to x264 when NVENC fails mid-encode
docs: explain how to install on Windows
perf(transcriber): reuse the loaded Whisper model between jobs
build(deps): bump faster-whisper to 1.2
refactor(ai)!: rename provider keys in settings.json

BREAKING CHANGE: settings saved by older versions must be re-entered
in Settings > Paid AI.
```

❌ Evite: `update`, `fix stuff`, `Adicionado botão`, `feat: Added new button.`

### Validação automática

O hook em [`.githooks/commit-msg`](.githooks/commit-msg) recusa mensagens fora do padrão e avisa quando a primeira
linha tem acentos (sinal de que não está em inglês). Ative uma vez por clone:

```bash
git config core.hooksPath .githooks
git config commit.template .gitmessage   # opcional: abre um modelo ao rodar "git commit"
```

## Pull requests

- Um PR por assunto. PRs pequenos são revisados mais rápido.
- Título do PR também no formato Conventional Commits (ex.: `feat(editor): add timeline zoom`).
- Descreva **o que muda**, **por quê** e **como testar**. Em mudanças de interface, inclua prints.
- Preencha o checklist do modelo de PR.
- Os PRs são integrados com **squash merge**: a mensagem final segue o título do PR.

## Estilo de código

- **Python**: 3.11+, com *type hints*, nomes e docstrings em português como no resto do projeto, e linhas de até 120
  caracteres.
- **TypeScript/React**: componentes funcionais. O lint usa o oxlint (`npm run lint` em `frontend/`).
- **Textos da interface**: em português do Brasil, simples e diretos, pensando em quem não é técnico.
- Mensagens de erro para quem usa devem dizer **como resolver**, não só o que deu errado.
- Prefira soluções que **rodam localmente e de graça**. Recursos pagos devem ser opcionais e mostrar o custo antes.

## O que não enviar

- Vídeos, cortes renderizados, capas, miniaturas ou qualquer coisa de `data/`.
- Chaves de API, `cookies.txt`, `.env` ou `settings.json`.
- Modelos de IA baixados (Whisper, Ollama).
- Conteúdo de terceiros sem permissão (inclusive em prints: borre rostos e miniaturas).

## Licença

Ao contribuir, você concorda que sua contribuição será distribuída sob a [licença MIT](LICENSE) do projeto.
