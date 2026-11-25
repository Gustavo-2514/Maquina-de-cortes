# Máquina de Cortes Local — Project Specification

[Português](MAQUINA_DE_CORTES.md) · **English**

> **For Claude Code:** this document is the complete project specification. Build it **phase by phase** (section 12), in order. At the end of each phase, run the project, check the acceptance criteria and only then move on. If anything here is ambiguous, pick the simplest option that works and record the decision in `DECISIONS.md`. Before starting, ask the user: **operating system** (Windows/Linux/macOS) and **whether they have an NVIDIA card (model/VRAM)**. The code must work with and without a GPU.

---

## 1. Overview

A **100% local** app (no paid APIs, no cloud) that works as a "homemade Opus Clip":

1. **Downloads** videos from links (YouTube, Twitch, TikTok, Instagram, X, etc.) — dedicated downloads area.
2. **Transcribes** the video with a timestamp for every word.
3. **Finds the best moments** with a local LLM and gives a "viral potential" score.
4. **Generates 9:16 vertical clips** with automatic reframing on the speaker's face.
5. **Adds animated captions** word by word.
6. **Lets you edit** each clip in an editor (adjust start/end, captions, style, framing, title) before exporting.
7. **Exports** MP4s ready for Shorts/Reels/TikTok.

Runs in the browser at `http://localhost:8000`, started with a single command.

### Out of scope (for now)
- Automatic posting to social networks.
- Multi-user, login, server deployment.
- AI video/image generation.

---

## 2. Stack (and why)

| Layer | Choice | Reason |
|---|---|---|
| Backend | **Python 3.11+ / FastAPI** | The whole AI/video ecosystem (Whisper, OpenCV, MediaPipe, yt-dlp) is Python. |
| Database | **SQLite + SQLModel** | Zero configuration, a single file, ideal for a local app. |
| Job queue | **Custom worker in a separate process** (reading the SQLite `jobs` table) | Avoids Redis/Celery. GPU jobs run one at a time. |
| Real-time progress | **Server-Sent Events (SSE)** | Simpler than WebSocket for server → client streams. |
| Download | **yt-dlp** (Python API) | Supports hundreds of sites. |
| Transcription | **faster-whisper** | Local Whisper, fast, with word-level timestamps. |
| LLM | **Ollama** (local HTTP) | Easy to install and swap models. Structured JSON output. |
| Vision | **OpenCV + MediaPipe Face Detection** + **PySceneDetect** | Lightweight face detection and scene-change detection. |
| Video | **FFmpeg** (system binary) | Cutting, encoding, captions (`ass` filter), mixing. |
| Frontend | **React + Vite + TypeScript** | An interactive editor needs rich components. |
| UI | **Tailwind CSS + shadcn/ui + lucide-react** | Modern look, fast. |
| State/data | **TanStack Query** (server) + **Zustand** (editor) | API cache + local editor state. |
| Timeline/waveform | **wavesurfer.js** (+ Regions plugin) | Waveform and dragging the clip's start/end. |

In production, FastAPI **serves the frontend build** (`frontend/dist`) — the user opens a single port.

---

## 3. System prerequisites

- Python 3.11+
- Node.js 20+ (only to develop/build the frontend)
- **FFmpeg** on the PATH (with `libass` enabled — official gyan.dev/BtbN builds on Windows already have it)
- **Ollama** installed and running (`ollama serve`), with a model downloaded:
  - With a GPU ≥ 8 GB: `qwen2.5:7b` or `llama3.1:8b`
  - No GPU / little VRAM: `qwen2.5:3b` or `llama3.2:3b`
- Optional NVIDIA GPU (CUDA + cuDNN for faster-whisper on the GPU)

The app must have a **diagnostics screen** (Settings) that checks each item above and shows ✅/❌ with instructions to fix it.

---

## 4. Folder structure

```
maquina-de-cortes/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, mounts routes and serves frontend/dist
│   │   ├── config.py            # Settings (pydantic-settings) + user's settings.json
│   │   ├── db.py                # SQLite engine, session
│   │   ├── models.py            # SQLModel: tables
│   │   ├── schemas.py           # request/response DTOs
│   │   ├── events.py            # SSE broker (in-memory pub/sub + DB polling)
│   │   ├── api/
│   │   │   ├── downloads.py
│   │   │   ├── projects.py
│   │   │   ├── clips.py
│   │   │   ├── jobs.py
│   │   │   ├── media.py         # file streaming with HTTP Range
│   │   │   └── system.py        # diagnostics, settings, presets
│   │   ├── services/
│   │   │   ├── downloader.py    # yt-dlp
│   │   │   ├── probe.py         # ffprobe
│   │   │   ├── proxy.py         # generates 540p proxy + waveform peaks + thumbnails
│   │   │   ├── transcriber.py   # faster-whisper
│   │   │   ├── highlighter.py   # Ollama + heuristics
│   │   │   ├── reframer.py      # face/scene → crop track
│   │   │   ├── captions.py      # generates .ass
│   │   │   ├── renderer.py      # builds the final ffmpeg command
│   │   │   └── hardware.py      # detects CUDA, NVENC, VRAM
│   │   └── worker/
│   │       ├── runner.py        # worker loop
│   │       └── tasks.py         # handlers per job type
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Downloads, Projects, Project, Editor, Queue, Settings
│   │   ├── components/
│   │   ├── editor/              # player, timeline, transcript, style panel, caption overlay
│   │   ├── api/                 # typed client + TanStack Query hooks
│   │   ├── stores/              # zustand
│   │   └── lib/
│   └── package.json
├── data/                        # (gitignored) everything the app generates
│   ├── app.db
│   ├── downloads/
│   ├── projects/<project_id>/
│   │   ├── source.mp4
│   │   ├── proxy.mp4
│   │   ├── audio.wav
│   │   ├── waveform.json
│   │   ├── transcript.json
│   │   ├── scenes.json
│   │   ├── faces.json
│   │   └── clips/<clip_id>/{captions.ass, crop.json, preview.jpg, final.mp4}
│   └── exports/
├── scripts/
│   ├── setup.(sh|ps1)           # creates venv, installs deps, builds frontend
│   └── start.(sh|bat)           # starts API + worker
├── run.py                       # starts API and worker together (subprocess)
├── DECISIONS.md
└── README.md
```

---

## 5. Data model (SQLModel)

```text
Download
  id, url, title, uploader, duration_s, thumbnail_url,
  format_choice ("best" | "1080p" | "720p" | "audio_mp3"),
  status ("queued"|"downloading"|"done"|"error"|"canceled"),
  progress (0-100), speed, eta, file_path, filesize, error,
  project_id (nullable — if it was sent to clipping), created_at

Project                         # a source video that will become clips
  id, name, source_path, origin ("download"|"upload"|"local_path"),
  duration_s, width, height, fps,
  language (default "pt"),
  status ("new"|"processing"|"ready"|"error"),
  stage ("probe"|"proxy"|"transcribe"|"analyze"|"done"),
  settings_json   # analysis options: number of clips, min/max duration, extra prompt
  created_at

Clip
  id, project_id, title, hook_text, reason,
  start_s, end_s,                 # editable
  score (0-100), score_breakdown_json  # {gancho, emoção, clareza, completude} = hook, emotion, clarity, completeness
  status ("suggested"|"edited"|"rendering"|"rendered"|"error"|"discarded"),
  reframe_mode ("auto"|"center"|"blur_fit"|"split"|"manual"),
  manual_crop_json,               # crop keyframes set in the editor
  caption_style_id, caption_overrides_json, # text corrected by the user
  title_overlay (fixed text at the top, optional),
  output_path, created_at, updated_at

CaptionStyle                    # caption presets
  id, name, font, font_size, primary_color, highlight_color,
  outline_color, outline_px, shadow_px, uppercase (bool),
  words_per_line (1-4), position_y (0-1), animation ("highlight"|"pop"|"none"),
  is_builtin

Job
  id, type ("download"|"probe_proxy"|"transcribe"|"analyze"|"reframe"|"render"),
  ref_id (download_id/project_id/clip_id), status ("queued"|"running"|"done"|"error"|"canceled"),
  progress, message, error, uses_gpu (bool), priority,
  created_at, started_at, finished_at
```

Large files (transcript, faces, peaks) are stored as **JSON on disk**, not in the database.

---

## 6. API (REST + SSE)

Prefix `/api`.

### Downloads
- `POST /downloads/info` `{url}` → metadata without downloading (title, duration, thumb, available formats). Uses `yt_dlp.YoutubeDL({"skip_download": True}).extract_info`.
- `POST /downloads` `{url, format_choice, send_to_project: bool}` → creates Download + Job.
- `GET /downloads` → history.
- `POST /downloads/{id}/cancel`, `DELETE /downloads/{id}` (with an option to delete the file).
- `POST /downloads/{id}/to-project` → creates a Project from the downloaded file.
- **Playlist** support: `info` detects it and returns a list; the user ticks which ones to download.

### Projects
- `POST /projects` → from a `download_id`, an **upload** (multipart, streamed in chunks) or a **local path** (`local_path`, to avoid copying huge files).
- `GET /projects`, `GET /projects/{id}`, `DELETE /projects/{id}`.
- `POST /projects/{id}/analyze` `{num_clips, min_s, max_s, extra_prompt, language}` → enqueues probe_proxy → transcribe → analyze (chained).
- `GET /projects/{id}/transcript` → words with timing.
- `PUT /projects/{id}/transcript` → manual word corrections.

### Clips
- `GET /projects/{id}/clips`
- `POST /projects/{id}/clips` → create a manual clip (start/end chosen by the user).
- `PATCH /clips/{id}` → any editable field.
- `POST /clips/{id}/render`, `POST /projects/{id}/render-all` (only the non-discarded ones).
- `POST /clips/{id}/duplicate`, `DELETE /clips/{id}`.
- `GET /clips/{id}/crop-track` → computed crop track (for the editor preview).

### Jobs / system
- `GET /jobs`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry`.
- `GET /events` → **SSE**: events `job.update`, `download.update`, `clip.update`, `project.update`.
- `GET /system/check` → ffmpeg, ffprobe, libass, ollama online, model present, CUDA, NVENC, disk space.
- `GET/PUT /system/settings`.
- `GET /caption-styles`, `POST/PATCH/DELETE /caption-styles/{id}`.
- `GET /media/{path}` → streaming with **HTTP Range support** (required for `<video>` to allow seeking). Restrict to paths inside `data/`.

---

## 7. Worker and queue

- Separate process (`python -m app.worker.runner`) that polls SQLite every ~0.5 s.
- **Two "slots"**: one for light I/O jobs (download, probe) — up to 2 concurrent; another for heavy jobs (`uses_gpu=True`: transcribe, analyze, reframe, render) — **1 at a time**, to avoid running out of VRAM.
- Each handler receives a `report(progress, message)` that updates the Job in the database; the API reads changes and publishes them over SSE.
- Cancellation: the handler checks `job.status == "canceled"` between steps; ffmpeg subprocesses are kept so they can be `terminate()`d.
- Jobs in `running` when the app restarts go back to `queued`.
- Models (Whisper) stay **cached in the worker** between jobs; free VRAM before calling Ollama if the GPU has < 10 GB (`del model; torch.cuda.empty_cache()` or recreate the `WhisperModel`).

---

## 8. Pipeline in detail

### 8.1 Download (`services/downloader.py`)
- `yt_dlp.YoutubeDL` with `progress_hooks` → `report()`.
- Formats:
  - `best`: `bv*+ba/b`, merged to mp4 (`merge_output_format: "mp4"`).
  - `1080p`: `bv*[height<=1080]+ba/b[height<=1080]`.
  - `720p`: same with 720.
  - `audio_mp3`: `ba` + FFmpegExtractAudio postprocessor, mp3 192k.
- Output template: `data/downloads/%(title).80s [%(id)s].%(ext)s`, sanitized names (`restrictfilenames` off, but `windowsfilenames: True`).
- Save title, uploader, duration, thumb.
- Common errors (private video, age restriction, geoblocking) → friendly message in PT-BR.
- Button in Settings: **"Update yt-dlp"** (runs `pip install -U yt-dlp`), because sites change frequently.
- Optional: field for `cookies.txt` (sites that require login).

### 8.2 Probe + proxy (`services/probe.py`, `proxy.py`)
- `ffprobe -v error -show_streams -show_format -of json` → duration, resolution, fps, codec, whether it has audio.
- Editor proxy: 540p, h264 `-preset veryfast -crf 28`, keyframe every 1 s (`-g <fps>`) for fast seeking.
- Audio: `ffmpeg -i source -ac 1 -ar 16000 audio.wav` (Whisper input).
- Waveform: compute peaks (e.g. 100 per second) with numpy from the wav → `waveform.json` (wavesurfer accepts precomputed `peaks` — avoids decoding large audio in the browser).
- Thumbnails: one frame every 10 s for the timeline strip (optional sprite).

### 8.3 Transcription (`services/transcriber.py`)
```python
from faster_whisper import WhisperModel
# GPU: ("large-v3", device="cuda", compute_type="float16")  |  VRAM < 6GB: ("medium", "cuda", "int8_float16")
# CPU: ("small", device="cpu", compute_type="int8")  (allow changing it in Settings)
segments, info = model.transcribe(
    "audio.wav", language=lang_or_None, word_timestamps=True,
    vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
    beam_size=5,
)
```
- Progress = `segment.end / duration`.
- Save `transcript.json`:
```json
{"language":"pt","segments":[{"id":0,"start":0.0,"end":4.2,"text":"...",
  "words":[{"w":"Olha","s":0.0,"e":0.31,"p":0.98}]}]}
```
- Post-processing: remove zero-duration words, attach stray punctuation to the previous word.

### 8.4 Highlight detection (`services/highlighter.py`)

**a) Preparation**
- Convert the transcript into numbered, timed lines: `[123.4–127.9] sentence text`.
- Long videos: ~8 min windows with 1 min of overlap. For each window, ask the LLM for up to `ceil(num_clips * 1.5 / n_windows) + 1` candidates.

**b) Ollama call** (`POST http://localhost:11434/api/chat`, `stream: false`, `format: <JSON schema>`, `options: {temperature: 0.3, num_ctx: 8192}`):

System prompt (written in PT-BR in the app; English translation below):
```
You are an expert editor of viral short videos (TikTok, Reels, Shorts).
You will receive the transcript of a video excerpt with timestamps.
Find the best moments to become standalone clips of {min_s} to {max_s} seconds.
A good clip:
- starts with a strong HOOK in the first 3 seconds (question, controversial statement, number, promise, conflict);
- is understandable on its own, without context from the rest of the video;
- has a beginning, middle and end (ends on a conclusion, punchline or complete sentence);
- has emotion, humor, strong opinion, a story or valuable information.
Avoid: introductions, subscribe requests, excerpts that depend on what came before.
Use ONLY timestamps that exist in the transcript.
{user_extra_prompt}
Reply only with the requested JSON.
```
Output schema (`gancho` = hook, `emocao` = emotion, `clareza` = clarity, `completude` = completeness):
```json
{"clips":[{"start":0.0,"end":0.0,"title":"string (up to 60 characters, catchy)",
  "hook":"string (first sentence of the clip)","reason":"string",
  "scores":{"gancho":0,"emocao":0,"clareza":0,"completude":0}}]}
```

**c) Post-processing (deterministic, in Python)**
- Validate the JSON; if it fails, retry once with temperature 0.
- **Snap edges**: move `start` to the start of the nearest word/sentence and `end` to the nearest end of sentence (punctuation `.?!` or a pause > 0.4 s). Add 0.15 s of breathing room at the end.
- Force the duration between `min_s` and `max_s` (extend/shorten to the next sentence boundary).
- Remove overlaps > 50% (the higher score wins).
- **Final score (0–100)** = 0.75 × weighted average of the LLM scores (hook 35%, completeness 25%, emotion 25%, clarity 15%) + 0.25 × heuristic:
  - audio energy (mean RMS of the excerpt vs. the video average),
  - speech rate (words/s around 2.5–3.5 is good),
  - few long silences.
- Sort by score and save the top N as `Clip(status="suggested")`.

### 8.5 9:16 reframing (`services/reframer.py`)

Per-project pre-analysis (done once, reused by every clip):
- **Scenes**: PySceneDetect `ContentDetector` → `scenes.json` (list of camera cuts).
- **Faces**: read the proxy at ~5 fps with OpenCV, MediaPipe Face Detection (full-range model, confidence ≥ 0.5) → `faces.json` with time-indexed normalized bounding boxes.

Per clip, generate a **crop track** (center X per frame, fixed width = height × 9/16):
1. For each sample, choose the target face: the largest; if there are several, prefer the one **moving its mouth** (variation of lip landmarks — optional/v2) or the one that appeared most in the scene.
2. No face → keep the last center; if there was never a face in the scene → center of the frame.
3. **Smoothing**: dead zone (only move if the target leaves ±8% of the crop width), then exponential smoothing (α ≈ 0.1 per sample) or a Savitzky-Golay filter. **On a scene change, reset without smoothing** (hard jump, like a real camera).
4. Interpolate to the video fps, clamp to the frame edges.
5. Save `crop.json` (the editor shows this rectangle over the preview and allows overriding it with manual keyframes).

Modes:
- `auto`: the track above.
- `center`: fixed center crop.
- `blur_fit`: the whole video centered (full width) over an enlarged, blurred copy of itself as background — good for screens/gameplay.
- `split`: two faces → top half and bottom half (when there are 2 stable faces for most of the clip).
- `manual`: user keyframes, linearly interpolated with easing.

Applying the crop at render time: for a **variable** crop, read frames from the source with OpenCV (at the original resolution), crop, resize to 1080×1920 and pipe raw (`bgr24`) to ffmpeg's stdin; the audio comes from the original file with `-ss/-to`. For `center`/`blur_fit`, use ffmpeg filters only (faster).

### 8.6 Captions (`services/captions.py`)
- Input: the clip's words (times relative to the clip `start`), with the user's corrections applied.
- Group into lines of `words_per_line` words (also break on punctuation and pauses > 0.35 s; max ~18 characters per line).
- Generate **ASS** with `PlayResX=1080, PlayResY=1920`:
  - `highlight`: for each word, a `Dialogue` event showing the whole line with the current word in `highlight_color` (via the `{\c&HBBGGRR&}` override) — colors in ASS are **BGR**.
  - `pop`: current word with `{\fscx115\fscy115}` → `\t` animation back to 100.
  - `uppercase`, outline, shadow, vertical position (`\pos` or `MarginV`).
- `title_overlay` becomes a second style at the top, for the whole clip (or only the first 3 seconds — option).
- Built-in presets (created on first start):
  - **Hormozi**: Montserrat ExtraBold, white, yellow highlight `#FFE600`, 6px black outline, uppercase, 2 words.
  - **Clean**: Inter Bold, white, soft shadow, 4 words, no highlight.
  - **Neon**: green highlight `#39FF14`, pop.
  - **Karaoke**: words already spoken change color.
- Fonts: bundle free `.ttf`s (Montserrat, Inter, Bebas Neue — OFL license) in `backend/assets/fonts/` and pass `fontsdir` to the `ass` filter.
- **Windows caveat**: in the `ass=` filter, the path needs escaping (`C\:/folder/file.ass`). Safer: run ffmpeg with `cwd` set to the clip folder and use the relative path `ass=captions.ass:fontsdir=fonts`.

### 8.7 Render (`services/renderer.py`)
- Output: 1080×1920, 30 fps (or the source fps if ≤ 60), H.264, AAC 48 kHz 192k, `-movflags +faststart`.
- Encoder: `h264_nvenc -preset p5 -cq 21` if NVENC is available; otherwise `libx264 -preset veryfast -crf 20`.
- Audio: `loudnorm=I=-14:TP=-1.5:LRA=11` (the social networks' standard) — option on by default.
- Accurate cutting: `-ss` **after** `-i` for the video (or before + re-encode), guaranteeing sync with the captions.
- Generate `preview.jpg` (middle frame) and save `output_path`.
- Final file name: `<score>_<title-slug>.mp4` in `data/exports/<project>/`.
- Progress: parse ffmpeg's `-progress pipe:1` (`out_time_ms`).

### 8.8 Hardware (`services/hardware.py`)
- CUDA: `ctranslate2.get_cuda_device_count() > 0`.
- NVENC: `ffmpeg -hide_banner -encoders` contains `h264_nvenc` **and** a quick 1-frame encode test works.
- VRAM: `nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits` (if available).
- Choose defaults (Whisper model, compute_type, encoder) from that; everything can be overridden in Settings.

---

## 9. Interface (frontend)

Layout: fixed sidebar with **Downloads · Projects · Queue · Settings**. Dark theme by default. Everything in PT-BR. Toasts for success/error. Updates via SSE (no manual refresh).

### 9.1 Downloads
- Large "Paste the link here" field + **Analyze** button → card with thumb, title, channel, duration.
- Quality selector (Best / 1080p / 720p / Audio only MP3) and a **"Send to clipping after download"** checkbox.
- Playlist: list with checkboxes + "Select all".
- List/history: progress bar, speed, ETA, status; actions: cancel, open folder, **Create clips**, delete.
- Accept several links at once (one per line).

### 9.2 Projects
- Card grid (thumb, name, duration, number of clips, status/stage with progress).
- **New project** button: from a download / upload (drag & drop) / local path.
- On creation, a **"Configure analysis"** modal: number of clips (default 10), min/max duration (default 20–60 s), language, default caption preset, default framing mode, "extra instructions for the AI" (e.g. "focus on the funny parts").

### 9.3 Project (list of suggested clips)
- Player for the original video (proxy) on the left; on the right, the list of clips sorted by score:
  - colored score badge (green ≥ 80, yellow ≥ 60, gray below), title, duration, hook, reason (expandable).
  - Click → plays the excerpt in the player.
  - Actions: **Edit**, **Render**, **Discard**, **Duplicate**.
- Buttons: **Render all**, **New manual clip**, **Re-analyze** (with other options).
- Filter: minimum score, status.

### 9.4 Clip editor (the main screen)

```
┌──────────────────────────────────────────────────────────────────────┐
│ ← Back   Clip title [editable]                     Score 87   [Render] │
├───────────────────────┬───────────────────────┬──────────────────────┤
│  16:9 source (proxy)  │  9:16 preview         │  Side panel          │
│  with a draggable     │  (crop + captions     │  (tabs)              │
│  crop rectangle       │   simulated in CSS)   │  • Captions          │
│                       │                       │  • Framing           │
│                       │                       │  • Text/Title        │
│                       │                       │  • Export            │
├───────────────────────┴───────────────────────┴──────────────────────┤
│ Timeline: waveform + thumbnail strip, clip region with start/end      │
│ handles, playhead, zoom; ±30 s of context outside the clip            │
├──────────────────────────────────────────────────────────────────────┤
│ Clip transcript: clickable words (click = seek;                       │
│ Shift+click = set start/end; double click = correct word)             │
└──────────────────────────────────────────────────────────────────────┘
```

Editor requirements:
- **Preview without rendering**: the proxy `<video>` is displayed inside a 9:16 container using `object-position`/transform computed from the crop track on `timeupdate`/`requestAnimationFrame`; captions are drawn in HTML/CSS on top, mimicking the ASS style (same font, colors, outline via `-webkit-text-stroke`/`text-shadow`, current-word highlight). It must be **faithful enough** for the user to decide without rendering.
- Timeline with wavesurfer.js + Regions: dragging the handles changes `start_s`/`end_s`; on release, "snap" to the nearest word boundary (can be disabled with Alt).
- Transcript: words outside the clip are grayed out; correcting a word's text saves to `caption_overrides_json` (doesn't change timings).
- **Captions** tab: choose preset, edit font/size/colors/words per line/position/uppercase/animation; "Save as new preset".
- **Framing** tab: mode (auto/center/blur/split/manual); in manual, drag the rectangle over the source and click **"Add keyframe"** at the current time; keyframe list with remove.
- **Text/Title** tab: fixed title at the top (on/off, only for the first 3 s or the whole clip).
- **Export** tab: quality, normalize audio, render button, link to open the file/folder when done.
- **Autosave** with debounce (800 ms) via `PATCH /clips/{id}`; undo/redo (Ctrl+Z / Ctrl+Shift+Z) in the Zustand store.
- Shortcuts: Space (play/pause), J/K/L, ←/→ (1 frame / Shift = 1 s), I/O (set start/end at the playhead), Ctrl+S (force save), Ctrl+Enter (render).

### 9.5 Queue
- Job table with type, target, progress, message, duration; cancel/retry; filter by status.

### 9.6 Settings
- **Diagnostics** (section 3) with a "Check again" button.
- Whisper model (tiny…large-v3, auto), device (auto/cuda/cpu), compute type.
- Ollama URL + model selector (list via Ollama's `GET /api/tags`) + "Test" button.
- Encoder (auto/nvenc/x264), export folder, default language.
- Update yt-dlp; `cookies.txt` path.
- Disk usage of `data/` + "Clean temporary files" button (proxies/wav of old projects).

---

## 10. Non-functional requirements

- **Everything local**: no external calls other than downloading videos and the initial model downloads.
- **Resilience**: each step saves its result to disk; re-analyzing or re-rendering does **not** redo steps that are already done (cache by file existence + hash of the options).
- **Target performance** (1 h video, 8 GB GPU): transcription < 5 min, analysis < 3 min, render of each 45 s clip < 30 s.
- **Without a GPU** it must work — just slower. Show a time estimate before analyzing.
- Logs in `data/logs/` (rotated), configurable level. Job errors show the cause in PT-BR + expandable technical details.
- Paths with accents/spaces must work (Windows especially). Always use `pathlib`.
- Basic security: the API listens only on `127.0.0.1`; `/media` must not serve anything outside `data/` (block `..`).

---

## 11. Tests

- `pytest` on the backend:
  - `captions.py`: word grouping, BGR colors, relative timings.
  - `highlighter.py`: edge snapping, overlap removal, duration clamping, invalid JSON parsing (with a mocked LLM).
  - `reframer.py`: smoothing, reset on scene change, frame bounds (with synthetic data).
  - `renderer.py`: building the ffmpeg command (without running it).
  - Integration test with a short video generated by ffmpeg (`testsrc` + `sine`) covering probe → render.
- Frontend: `vitest` for utilities (crop calculation in the preview, caption grouping — **same logic as the backend**, ideally sharing test cases in JSON).

---

## 12. Implementation phases

Each phase ends with the app running and the criteria met.

**Phase 0 — Skeleton**
- Folder structure, FastAPI with `/api/system/check`, Vite + Tailwind + shadcn frontend with layout and empty routes, `run.py` starting API + worker, setup/start scripts.
- ✅ `python run.py` opens the UI at localhost:8000 and the Settings screen shows the real diagnostics.

**Phase 1 — Downloads**
- Tables, worker/queue, SSE, downloader with progress, complete Downloads page (incl. playlists and multiple links).
- ✅ Paste a YouTube link, see real-time progress, the file appears in `data/downloads/`, cancel works.

**Phase 2 — Projects + transcription**
- Create a project (download/upload/local path), probe, proxy, wav, waveform, transcription with progress; `/media` endpoint with Range.
- ✅ A 10 min video becomes a project and the word-level transcript appears on the project screen.

**Phase 3 — Highlights**
- highlighter with Ollama + post-processing + score; list of suggested clips on the project page, playing the excerpt in the player.
- ✅ Generates N coherent clips, with edges at sentence ends, no overlap, sorted by score.

**Phase 4 — Basic render**
- Render with center crop + ASS captions (Hormozi preset) + loudnorm + NVENC/x264; Queue page.
- ✅ "Render all" produces 1080×1920 MP4s that play on a phone with synced captions.

**Phase 5 — Reframing**
- Scenes + faces + smoothed track; auto, blur_fit, split modes.
- ✅ In a podcast with 2 people, the crop follows whoever is on screen without shaking, and jumps cleanly on camera cuts.

**Phase 6 — Editor**
- Complete editor screen (section 9.4): preview with simulated crop and captions, timeline with handles, clickable transcript, tabs, autosave, undo, shortcuts, manual keyframes.
- ✅ Adjusting start/end, changing the style and correcting a word are reflected in the preview instantly and in the final MP4.

**Phase 7 — Polish**
- Extra presets, title at the top, manual clip from scratch, temporary file cleanup, time estimate, friendly error messages, README with step-by-step installation for non-technical users.
- ✅ A new user can install it by following only the README.

**Ideas for later (v2)**
- Speaker detection (diarization with pyannote or lip movement) so the crop follows the voice.
- Automatic B-roll/emoji, punch-in zoom on emphasized words.
- Removal of silences and "uh/um" filler (jump cuts).
- Caption translation, packaging as a desktop app (Tauri/PyInstaller).
- Integration with the "AI studio" (other automation modules in the same app).

---

## 13. Usage note

Only download and clip content you have the right to use (your own, licensed, or with the creator's permission). Some platforms only allow monetizing third-party clips with authorization.
