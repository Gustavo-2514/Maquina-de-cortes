<div align="center">

<img src="maquina-de-cortes/frontend/public/brand/logo.svg" alt="Máquina de Cortes" width="88">

# Máquina de Cortes ✂️

[Português](README.md) · **English**

**Long video in, viral clips out.**

Turns podcasts, livestreams, lectures and gameplay into vertical clips for TikTok, Reels and Shorts,
with animated captions and automatic framing. Runs on your own computer, for free, without sending your videos to the cloud.

### 👉 [Full guide: installation, usage and AI models](maquina-de-cortes/README.en.md)

</div>

![Máquina de Cortes home screen](maquina-de-cortes/docs/img/inicio.webp)

> The app's interface is in Brazilian Portuguese.

## Quick start (Linux)

```bash
git clone https://github.com/Gustavo-2514/ai-studio.git
cd ai-studio/maquina-de-cortes
scripts/setup.sh              # installs everything (only once, 10–40 min)
scripts/sugerir-modelos.sh    # optional: shows the ideal AI models for your PC
scripts/start.sh              # opens at http://localhost:8000
```

Windows, macOS, requirements, step-by-step with screenshots and troubleshooting: see the [full guide](maquina-de-cortes/README.en.md).

## What's in this repository

| Folder / file | Contents |
|---|---|
| [`maquina-de-cortes/`](maquina-de-cortes/) | the app (Python backend + React interface) |
| [`MAQUINA_DE_CORTES.en.md`](MAQUINA_DE_CORTES.en.md) | original project specification |
| [`CHANGELOG.en.md`](CHANGELOG.en.md) | what changed in each version |
| [`CONTRIBUTING.en.md`](CONTRIBUTING.en.md) | how to contribute and commit conventions |

[MIT](LICENSE) license. Made by [Gustavo Albuquerque](https://github.com/Gustavo-2514).
