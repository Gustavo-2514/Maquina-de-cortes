# Changelog

[Português](CHANGELOG.md) · **English**

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [semantic versioning](https://semver.org/).

> The Portuguese [`CHANGELOG.md`](CHANGELOG.md) is the source of truth; this file mirrors it.

## [Unreleased]

### Fixed

- **Try again** after an AI analysis error now resumes from the window that failed: answers for windows already
  read are kept in the project and reused (same model and options). The cache is deleted when the analysis
  finishes, so **Reanalyze** still asks for fresh suggestions.
- Ollama now has a 2048-token cap per answer; before, a model stuck in a loop produced hundreds of KB of text
  and the analysis failed with "The LLM did not return valid JSON".
- Videos with very dense speech (debates, crowded podcasts) always failed on the same window: the request went
  past the 8192-token context, Ollama silently cut its beginning (the instructions) and the model returned
  garbage. The request size is now estimated before sending and, only when it does not fit, the context is raised
  up to the installed model's maximum (read from Ollama); if it still does not fit, the window is split in two.
- **Split screen (Debate)** now decides moment by moment: with two people in frame it splits (left on top, right
  at the bottom); when only one shows up, they fill the whole screen, centered. Before, the decision applied to the
  whole scene and the same person could appear on top and at the bottom (one face matched both sides); now it only
  splits with two different faces, not overlapping and apart horizontally. Stretches shorter than 1 s are absorbed
  by their neighbor, so a brief detection miss does not make the screen flicker.

## [1.0.0] - 2026-11-26

### Added

- Contribution guide (`CONTRIBUTING.md`), Conventional Commits standard enforced by a hook
  (`.githooks/commit-msg`), commit message template (`.gitmessage`) and pull request template.
- English versions of all Markdown documents (`*.en.md`).
- Download quality choice (best, 1080p or 720p) right on the Home screen, before pasting the link.
  The last choice is remembered and also applies on the Downloads screen.
- Rendering as a pipeline stage: clicking **Criar cortes** on Home opens a dialog asking the video type
  (General, Gameplay, Podcast, Debate) and whether to render the clips right away. When enabled, the project runs
  on its own until the final MP4s ("Render clips" stage) and only becomes "Ready" when the last render finishes.
  The same option is available in the analysis settings and on the Downloads screen.

### Changed

- New minimal design system (`maquina-de-cortes/docs/DESIGN_SYSTEM.en.md`): three colors (black `#000000`,
  white `#ffffff` and red `#df2531` for emphasis only), Poppins typeface, no shadows and grayscale illustrations.
  Logo and favicon redrawn in the new palette.
- Interface polish following Vercel's Web Interface Guidelines: "skip to content" link, micro-interactions on
  buttons, cards and links, a single hero entrance, pause control on the background video, error messages that say
  what to do, and an icon-only sidebar on narrow screens.
- Template cards (General, Gameplay, Podcast and Debate) in the "Configure analysis" and "Render all" windows
  now have illustrated covers showing the original video turning into the vertical clip.

## [0.1.0] - 2026-11-25

First public release of **Máquina de Cortes**.

### Added

- **Downloads** from links (YouTube, Twitch, TikTok, Instagram, X and others, via yt-dlp): queue, real-time progress,
  cancel, resume after restart, playlists, quality selection and MP3 audio.
- **Projects** from a download, a file upload or a local path.
- Word-level **transcription** with Whisper (faster-whisper), on the NVIDIA GPU or the CPU, with manual word
  correction.
- **Local AI analysis** (Ollama + Qwen 2.5): picks the best moments, gives a viral-potential score and explains why.
  Minimum and maximum duration per clip (default 60–90 s) and extra instructions for the AI.
- **Time estimate** for the analysis before it starts, based on the hardware.
- **9:16 framing**: follow face (YuNet), speaker in the center (lip reading with MediaPipe), webcam + game,
  split screen, full frame with blurred background, center and manual, with camera-cut detection (PySceneDetect).
- **Templates per video type**: General, Gameplay, Podcast and Debate.
- **Animated captions** in 7 styles (Hormozi, Clean, Neon, Karaoke, Impact, Minimal and Yellow), adjustable per clip.
- **Editor** with vertical preview, timeline with waveform, clickable transcript, undo/redo,
  autosave and keyboard shortcuts.
- **Render** with NVENC (or x264), audio normalized to −14 LUFS and "Render all".
- **Posting pack**: title, caption and hashtags for TikTok, Reels and Shorts, automatic cover and
  "Export all (.zip)" with MP4s, covers, `textos.csv` and `textos.txt`.
- **Optional paid AI** via API key (Claude, OpenRouter, OpenAI, Gemini, DeepSeek, xAI, Groq, Mistral or any
  OpenAI-compatible API) for the analysis and for the **visual review** of clips, always with an estimated cost before
  and the actual cost after.
- **Settings** with system diagnostics, model selection, storage (temporary file cleanup),
  yt-dlp updates and `cookies.txt`.
- **Installers** without sudo for Linux (`scripts/setup.sh`), plus Windows (`setup.ps1`) and macOS (untested).
- **`scripts/sugerir-modelos`**: suggests the ideal transcription and AI models for each person's computer and,
  with `--aplicar`, configures the app and downloads the model.
- Full README with a beginner-friendly walkthrough, screenshots and an explanation of the models.
- MIT license.

[Unreleased]: https://github.com/Gustavo-2514/ai-studio/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Gustavo-2514/ai-studio/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/Gustavo-2514/ai-studio/releases/tag/v0.1.0
