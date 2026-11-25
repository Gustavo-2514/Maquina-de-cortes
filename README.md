<div align="center">

<img src="maquina-de-cortes/frontend/public/brand/logo.svg" alt="Máquina de Cortes" width="88">

# Máquina de Cortes ✂️

**Vídeo longo entra, cortes virais saem.**

Transforma podcasts, lives, aulas e gameplays em cortes verticais para TikTok, Reels e Shorts,
com legenda animada e enquadramento automático. Roda no seu computador, de graça e sem mandar seus vídeos para a nuvem.

### 👉 [Guia completo: instalação, uso e modelos de IA](maquina-de-cortes/README.md)

</div>

![Tela inicial da Máquina de Cortes](maquina-de-cortes/docs/img/inicio.webp)

## Começo rápido (Linux)

```bash
git clone https://github.com/Gustavo-2514/ai-studio.git
cd ai-studio/maquina-de-cortes
scripts/setup.sh              # instala tudo (uma vez só, 10–40 min)
scripts/sugerir-modelos.sh    # opcional: mostra os modelos de IA ideais para o seu PC
scripts/start.sh              # abre em http://localhost:8000
```

Windows, macOS, requisitos, passo a passo com prints e solução de problemas: veja o [guia completo](maquina-de-cortes/README.md).

## O que tem neste repositório

| Pasta / arquivo | Conteúdo |
|---|---|
| [`maquina-de-cortes/`](maquina-de-cortes/) | o aplicativo (backend Python + interface React) |
| [`MAQUINA_DE_CORTES.md`](MAQUINA_DE_CORTES.md) | especificação original do projeto |
| [`CHANGELOG.md`](CHANGELOG.md) | o que mudou em cada versão |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | como contribuir e padrão de commits |

Licença [MIT](LICENSE). Feito por [Gustavo Albuquerque](https://github.com/Gustavo-2514).
