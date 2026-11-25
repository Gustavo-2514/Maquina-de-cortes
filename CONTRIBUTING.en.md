# How to contribute

[Português](CONTRIBUTING.md) · **English**

Thanks for your interest in improving **Máquina de Cortes**! This guide explains how to report problems, suggest ideas
and submit code.

## Contents

- [Ways to contribute](#ways-to-contribute)
- [Reporting a problem](#reporting-a-problem)
- [Setting up the environment](#setting-up-the-environment)
- [Workflow](#workflow)
- [Commit convention (Conventional Commits)](#commit-convention-conventional-commits)
- [Pull requests](#pull-requests)
- [Code style](#code-style)
- [What not to submit](#what-not-to-submit)

## Ways to contribute

- **Test on Windows or macOS**: the scripts exist but have barely been tested. Reports help a lot.
- **Report bugs** and **suggest features** through *issues*.
- **Improve the documentation**: if something in the README wasn't clear to you, it probably isn't clear to others.
- **Submit code**: fixes, new features, tests.

For large changes (new feature, swapping a library, architecture changes), **open an issue first** so we can
talk it over. That way nobody wastes time on something that won't be merged.

## Reporting a problem

Open an *issue* with:

1. **What happened** and **what you expected**.
2. **Steps to reproduce.**
3. **Your environment**: OS (e.g. Ubuntu 24.04, Windows 11), graphics card and RAM.
4. The diagnostics output: `.venv/bin/python run.py --diagnostico` (inside `maquina-de-cortes`).
5. The error's **Technical details** (on the **Fila** / Queue screen) or the relevant excerpt from `data/logs/`.

> Don't paste API keys, cookies or paths containing personal data.

## Setting up the environment

```bash
git clone https://github.com/Gustavo-2514/ai-studio.git
cd ai-studio

# Enables commit message validation and the message template (once per clone)
git config core.hooksPath .githooks
git config commit.template .gitmessage

cd maquina-de-cortes
scripts/setup.sh                       # installs everything
.venv/bin/python run.py --dev          # API on :8000 and hot-reloading interface on :5173
```

Main structure:

| Folder | Contents |
|---|---|
| `maquina-de-cortes/backend/app/api/` | HTTP routes (FastAPI) |
| `maquina-de-cortes/backend/app/services/` | transcription, AI, framing, render, captions… |
| `maquina-de-cortes/backend/app/worker/` | job queue |
| `maquina-de-cortes/backend/tests/` | backend tests (pytest) |
| `maquina-de-cortes/frontend/src/` | interface (React + TypeScript + Tailwind) |
| `maquina-de-cortes/scripts/` | installers and utilities |

Implementation decisions and measurements live in [`maquina-de-cortes/DECISIONS.en.md`](maquina-de-cortes/DECISIONS.en.md).
If your change involves a non-obvious choice, record it there too (in the Portuguese file, which is the source of truth).

### Running the tests

```bash
cd maquina-de-cortes/backend && ../.venv/bin/pytest
cd maquina-de-cortes/frontend && npm test && npx tsc -b
```

## Workflow

1. **Fork** the repository and create a branch from `main`:
   ```bash
   git checkout -b feat/timeline-zoom
   ```
   Branch names: `<type>/<short-description>`, for example `fix/nvenc-fallback`, `docs/windows-setup`.
2. Make small, focused commits following the [commit convention](#commit-convention-conventional-commits).
3. Run the tests.
4. Update the README and [`CHANGELOG.md`](CHANGELOG.md) (**Não lançado** / Unreleased section) if the change is visible to users.
5. Open the **pull request** against `main`.

## Commit convention (Conventional Commits)

All commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and are **written in
English**.

```text
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

### Rules

- **type** is required, lowercase (table below).
- **scope** is optional, in parentheses: the part of the project affected.
- **description** in English, in the **imperative** ("add", not "added" or "adds"), starting with a lowercase letter,
  **no trailing period**.
- The first line is at most **72 characters**.
- The body (optional) explains **what** and **why**, not how. Wrap lines at 72 characters.
- **Breaking changes**: `!` after the type/scope and a `BREAKING CHANGE: ...` footer.
- Reference issues in the footer: `Closes #42`.

### Types

| Type | When to use | Goes into the CHANGELOG as |
|---|---|---|
| `feat` | new user-facing feature | Added |
| `fix` | bug fix | Fixed |
| `docs` | documentation only | — |
| `style` | formatting, no behavior change | — |
| `refactor` | code reorganization, no behavior change | — |
| `perf` | performance improvement | Changed |
| `test` | new or fixed tests | — |
| `build` | dependencies, packaging, install scripts | Changed (if it affects users) |
| `ci` | continuous integration | — |
| `chore` | maintenance that doesn't fit the above | — |
| `revert` | reverts a previous commit | — |

### Suggested scopes

`ui`, `editor`, `api`, `worker`, `transcriber`, `highlighter`, `reframer`, `render`, `captions`, `downloads`,
`postpack`, `ai`, `scripts`, `deps`.

### Examples

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

❌ Avoid: `update`, `fix stuff`, `Adicionado botão`, `feat: Added new button.`

### Automatic validation

The hook in [`.githooks/commit-msg`](.githooks/commit-msg) rejects messages that don't follow the convention and warns
when the first line has accented characters (a sign it isn't in English). Enable it once per clone:

```bash
git config core.hooksPath .githooks
git config commit.template .gitmessage   # optional: opens a template when you run "git commit"
```

## Pull requests

- One PR per topic. Small PRs get reviewed faster.
- PR titles also use the Conventional Commits format (e.g. `feat(editor): add timeline zoom`).
- Describe **what changes**, **why** and **how to test**. For interface changes, include screenshots.
- Fill in the PR template checklist ([English version](.github/pull_request_template.en.md)).
- PRs are merged with **squash merge**: the final message follows the PR title.

## Code style

- **Python**: 3.11+, with *type hints*, names and docstrings in Portuguese like the rest of the project, and lines of up
  to 120 characters.
- **TypeScript/React**: function components. Linting uses oxlint (`npm run lint` in `frontend/`).
- **Interface text**: in Brazilian Portuguese, simple and direct, written for non-technical people.
- User-facing error messages must say **how to fix it**, not just what went wrong.
- Prefer solutions that **run locally and for free**. Paid features must be optional and show the cost upfront.

## What not to submit

- Videos, rendered clips, covers, thumbnails or anything from `data/`.
- API keys, `cookies.txt`, `.env` or `settings.json`.
- Downloaded AI models (Whisper, Ollama).
- Third-party content without permission (including in screenshots: blur faces and thumbnails).

## License

By contributing, you agree that your contribution will be distributed under the project's [MIT license](LICENSE).
