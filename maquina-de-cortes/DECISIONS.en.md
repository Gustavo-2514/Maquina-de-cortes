# Decisions

[Português](DECISIONS.md) · **English**

Record of choices where the specification was ambiguous or the environment required adaptation.

> The Portuguese [`DECISIONS.md`](DECISIONS.md) is the source of truth; this file mirrors it. Some identifiers
> (CLI flags, query parameters, UI labels) are in Portuguese because that is what the code actually uses.

## Phase 0
- **Reference environment**: Ubuntu 26.04, RTX 3050 8 GB. The system Python is 3.14 without `ensurepip`;
  MediaPipe/ctranslate2 tend to lag behind with wheels for new Python versions → the project uses
  **Python 3.12 via `uv`** (fallback: `python3.11+ -m venv`).
- The **virtual environment** lives in `.venv/` at the root; `scripts/start.sh` uses that Python.
- **Logging**: `setup_logging()` in `app/logging_setup.py` (separate from `main.py` so the worker
  doesn't import FastAPI). Files in `data/logs/{api,worker}.log`, rotation 5 MB × 3.
- **Configuration**: infrastructure via `MDC_*` env vars (`MDC_PORT`, `MDC_DATA_DIR`...);
  user preferences in `data/settings.json` (GET/PUT `/api/system/settings`).
- **Dev mode**: `python run.py --dev` also starts Vite on :5173 with a `/api` → :8000 proxy.
- **shadcn/ui**: base components (button, card, badge) hand-written following the shadcn pattern
  (Tailwind v4 + `cn()`), with `components.json` so that `npx shadcn add <x>` works later.
- **Toasts**: `sonner` (what shadcn recommends).
- **NVENC**: considered available only if a real 1-frame encode works (result cached
  per process).

## Environment installation (no sudo)
- Everything installed in user space, without `sudo`:
  - `uv` → `~/.local/bin/uv`; Python 3.12 managed by uv; venv in `.venv/`.
  - **Static FFmpeg 8.1** (BtbN/FFmpeg-Builds, GPL) in `~/.local/opt/`, links in `~/.local/bin/{ffmpeg,ffprobe}`.
    It has libass and NVENC (Ubuntu's apt ffmpeg has no NVENC).
  - **Ollama** (official tarball) in `~/.local/opt/ollama`, link in `~/.local/bin/ollama`. Models in `~/.ollama`.
- `run.py` prepares the child processes' environment: puts `~/.local/bin` on the PATH, adds the venv's
  `nvidia/*/lib` libs to `LD_LIBRARY_PATH` (cuBLAS 12 / cuDNN 9 for ctranslate2) and **starts
  `ollama serve` if it isn't running** (and stops it on exit, only if it started it). Log in `data/logs/ollama.log`.
- The CUDA diagnostic only shows ✅ if `libcublas.so.12` and `libcudnn.so.9` actually load.
- `av<17`: PyAV 17+ removed the `metadata_errors` argument that faster-whisper 1.2.1 uses.
- All Python dependencies for phases 1–5 installed up front (complete requirements.txt).
- Pre-downloaded models: `qwen2.5:7b` (Ollama) and Whisper `large-v3` (Hugging Face cache).
- **Static** caption fonts (not variable — libass resolves weights of variable fonts poorly):
  Montserrat Bold/ExtraBold/Black, Inter SemiBold/Bold/ExtraBold, Bebas Neue (all OFL).
- `mediapipe` pulls in `opencv-python` alongside `-headless`; both coexist for now — revisit in Phase 5 if they conflict.
- **VRAM (RTX 3050 8 GB)**: `qwen2.5:7b` takes ~4.6 GB and Whisper `large-v3` fp16 ~3.7 GB — **they don't fit together**
  (tested: OOM). Rule for the worker (Phase 2/3): before transcribing, unload the Ollama model
  (`POST /api/generate {"model": ..., "keep_alive": 0}`); after transcribing, release Whisper before
  calling the LLM. GPU jobs already run 1 at a time (section 7).

## Phase 1 — Downloads
- **Queue** = the `job` table. `app/queue.py` centralizes enqueue/cancel/retry/claim (atomic claim via
  `UPDATE … WHERE status='queued'`). Worker: light `ThreadPoolExecutor` (2) + GPU (1).
- **Cancellation**: the API marks `canceled`; the worker loop (0.5 s) sees the job is no longer `running`
  (canceled *or deleted*) and calls `JobContext.cancel()` → event + `terminate()` of the subprocesses.
  yt-dlp's progress hook checks the event and aborts; `.part` files/fragments are deleted.
- **App shutdown** ≠ cancellation: in-progress jobs go back to `queued` (and the download to `queued`)
  and are resumed on restart. If the worker dies without shutting down, `recover_interrupted()` at startup does the same.
- **SSE**: the API receives nothing directly from the worker; polling of `updated_at` (0.5 s, 1 s window
  with deduplication by `(table, id, updated_at)`) publishes `job.update`/`download.update`. The frontend applies
  the events directly to the TanStack Query cache and invalidates everything on reconnect.
- **Dates** in UTC with timezone (current SQLModel requires "aware" datetimes).
- **YouTube** requires solving JS challenges: `yt-dlp[default]` (includes `yt-dlp-ejs`) + the `node` runtime
  (yt-dlp's default is `deno`, which isn't installed). `base_opts()` enables whichever exist.
- **DASH progress**: video and audio are downloaded in sequence; formats are resolved beforehand
  (`extract_info(download=False)` → `process_ie_result`) and progress is weighted by the size of each part.
  100% only when the job finishes (post-processing stays at 99%).
- **Batch**: `POST /downloads/batch` (several links/playlist entries in one call), in addition to `POST /downloads`.
- yt-dlp **errors** become a PT-BR message (`friendly_error`) + expandable technical details in the UI.
- **"Send to clipping"** is already stored (`Download.send_to_project`), but project creation arrives in Phase 2;
  the "Create clips" button stays disabled until then.
- **Open folder**: `POST /system/open-folder` (xdg-open/open/explorer), restricted to `data/`.
- **Update yt-dlp**: `uv pip install -U yt-dlp[default]` (or pip); requires restarting the app.
- Deleting a download also deletes its jobs; "list + file" refuses if the file belongs to a project.

## Phase 2 — Projects + transcription
- **Source without copying**: download and local-path projects point to the original file
  (`source_path`); only uploads are written to `data/projects/<id>/source.<ext>`. Deleting a project removes
  only its own folder (derivatives + upload). A download with a project can't have its file deleted.
- **Upload** streamed with a raw body (`POST /projects/upload?filename=…`, no multipart) and progress via XHR.
- **"Create clips"** (Downloads) = `POST /downloads/{id}/to-project` → opens the project with `?configurar=1`,
  which shows the "Configure analysis" modal. Audio-only downloads don't become projects.
- **Pipeline**: `probe_proxy` (light slot) → `transcribe` (GPU slot). The `analyze` job arrives in Phase 3; for now
  the project becomes `ready` after transcription. Analysis options live in `settings_json`.
- **Cache**: `meta.json` stores the source signature (path+size+mtime); re-analyzing doesn't redo proxy/wav/
  waveform/thumbs. The transcript is reused if the requested language is the same.
- **Proxy** with NVENC when available (falls back to libx264 if it fails); keyframe every ~1 s; max height 540.
- **Waveform**: normalized absolute peaks, 100/s, read from the WAV in 1 min blocks (constant memory).
- **Whisper**: `auto` → large-v3/float16 on the GPU (≥ 6 GB), otherwise CPU small/int8; if loading on the GPU fails,
  falls back to CPU. Before transcribing on the GPU, unloads the Ollama models (`/api/ps` + `keep_alive: 0`).
  The model stays cached in the worker between jobs (`release_model()` exists for Phase 3).
- **Transcript correction** (`PUT /transcript`) only changes word text; timings/structure are preserved.
- **Reused IDs**: SQLite reuses ids of deleted projects, so deleting a project deletes all of its
  jobs; the worker interrupts a running job whose record disappeared.
- **/media**: Starlette's `FileResponse` already handles Range (206); path resolved and restricted to `data/`.

## Phase 3 — Highlights
- **Chaining**: `transcribe` → `analyze` (GPU slot). Before the LLM, the worker releases Whisper if the GPU has
  < 10 GB (or isn't detected); before transcribing, it unloads Ollama. The two are never in VRAM together.
- **Ollama** via `/api/chat` with **streaming** and `format` = JSON schema (allows canceling mid-generation and
  showing progress per window). `num_ctx 8192`, temperature 0.3 → if the JSON is invalid, retries once with 0.
- LLM scores requested **from 0 to 10** (the spec shows `0` with no scale); values > 10 are treated as a 0–100 scale.
  Final score = 0.75 × weighted LLM (hook 35 / completeness 25 / emotion 25 / clarity 15, ×10) + 0.25 × heuristic
  (mean RMS energy vs. video average, pace of 2.5–3.5 words/s and silences > 0.7 s).
- **Edges**: sentence = ends in `.?!…` or a pause > 0.4 s. Start/end snap to the nearest sentence boundary (4 s radius);
  after adjusting the duration, if the end still falls mid-sentence, it is swapped for the nearest sentence end that respects
  [min, max] (no radius limit). 0.15 s of breathing room at the end, without overlapping the next word.
- **Overlap** measured relative to the shorter clip; > 50% → the higher score wins.
- `hook_text` = the clip's actual first sentence (after adjustment), not the LLM's "hook", which may not match the edges.
- **Re-analysis** only deletes AI clips that are still `suggested`/`discarded`; edited, rendered and manual ones stay.
- **Manual clip**: `origin="manual"`, `status="edited"`, score 0 (shown as "manual" in the list).
- Quality note (qwen2.5:7b): scores end up compressed (almost all 80–89, the LLM gives a hook score of 9 to almost
  everything). The ordering is still useful; if it becomes a problem, scores can be normalized by rank in Phase 7.
- Measured performance: 17.8 min video (3 windows) → analysis in ~75 s on the RTX 3050.

## Phase 4 — Basic render
- **Automatic migration**: `init_db()` compares models × tables and runs `ALTER TABLE ADD COLUMN` with the model's
  default (`create_all` doesn't alter existing tables). Doesn't drop/rename columns.
- **CaptionStyle**: built-in presets (`key` = hormozi/clean/neon/karaoke) created at startup; not editable —
  "save as new preset" creates a user style. Colors stored as `#RRGGBB`; conversion to ASS BGR
  happens in `captions.py`. Clip style: `caption_style_id` → otherwise the preset chosen in the analysis → Hormozi.
- **"karaoke" animation** added (the spec lists highlight/pop/none, but the Karaoke preset needs it).
- **Captions**: positioned with `\an5\pos(540, position_y×1920)`; lines break on word count, punctuation,
  pause > 0.35 s or > 18 characters; a line stays on screen until the next one if the gap is ≤ 0.6 s.
  Per-clip corrections in `caption_overrides_json` = `{"<word start with 3 decimals>": "text"}` (empty text
  removes the word from the captions). `title_overlay` appears at the top in a white box for the whole clip.
- **Fonts** verified in the libass log (`fontselect`): Montserrat ExtraBold/Black and Inter match the .ttf files
  in `assets/fonts` (no fallback). ffmpeg runs with `cwd` in the clip folder and `ass=captions.ass:fontsdir=<abs>`
  (value escaped for the filtergraph).
- **Accurate cutting**: `-ss` before `-i` + re-encode (accurate and fast; timestamps start at 0 = .ass timings).
- **Framing**: `center` (largest centered 9:16 rectangle; also works with a vertical source) and `blur_fit`
  with filters only. `auto`/`split`/`manual` use `center` until Phase 5.
- **Encoder**: NVENC p5 cq21 / x264 veryfast crf20, both with an **8 Mbps cap** (without a cap they produced ~15 Mbps
  from an upscaled 720p source). NVENC failure → tries x264. fps = source if ≤ 60, otherwise 30. Audio loudnorm −14 LUFS
  (`normalize_audio` setting), AAC 48 kHz 192k, `+faststart`.
- **Render cache**: hash of (spec + .ass + source signature + `RENDER_VERSION`) in `clips/<id>/render.json`;
  same hash and the MP4 exists → doesn't render. Title/score changed → file renamed and the old one deleted.
- **Output**: `<export_dir or data/exports>/<project-slug>-<id>/<score>_<title-slug>.mp4` (`_<id>` suffix only if
  another clip already uses the name). `GET /clips/{id}/file` serves the MP4 (Range; `?download=1` to download).
- Editing a rendered clip → status `edited` (UI shows "MP4 out of date").
- `run.py`: uvicorn with `--timeout-graceful-shutdown 3` (open SSE connections were holding up shutdown).
- Measured (RTX 3050, 720p60 source): 10 clips of 23–60 s in 123 s (7–16 s each); −14.4 LUFS; captions in sync.

## Phase 5 — Reframing
- **Face detector: YuNet (OpenCV `FaceDetectorYN`)**, not MediaPipe. MediaPipe 1.2 no longer has the legacy
  API (`solutions`) nor the spec's "full-range" model; the Tasks API only offers `blaze_face_short_range`
  (made for selfies). Compared on the test podcast, at 1 frame/6 s: YuNet found a face in 67/85 frames,
  MediaPipe in 54/85 (it missed profiles and smaller faces in wide shots). YuNet: ~14 ms/frame at 960×540 on the CPU.
  Models in `backend/assets/models/` (YuNet in use; the MediaPipe .tflite is kept only for the comparison).
  `mediapipe` was removed from requirements.
- **Pre-analysis** = `reframe` job on the **light slot** (CPU), enqueued together with transcription (runs in parallel
  with Whisper on the GPU). The spec marked reframe as GPU, but nothing here uses the GPU. Results in `scenes.json`
  (scene changes) and `faces.json` (faces at 5 fps, normalized to the original frame, even with a source ≠ 16:9).
  `Project.faces_ready`. If the render needs it and the analysis doesn't exist, it is done on the spot.
- **Frames for detection** decoded by ffmpeg (`fps=5`, bgr24 pipe) instead of OpenCV `VideoCapture`:
  faster, and each sample's timestamp is exact (i/5).
- **Scenes**: PySceneDetect `ContentDetector(27)`, in 60 s blocks (progress + cancellation). ~39 s for 18 min.
- **Target per scene**: faces grouped by X position; the dominant group (sum of areas = largest + most present)
  is followed. Faces < 3.5% of the height are ignored. Scene with no face → center.
- **Smoothing**: starts at the median of the first second (no ramp), dead zone of 8% of the crop width and
  exponential α = 0.2 per sample (the spec suggests ≈ 0.1; at 5 fps that gave ~2 s of lag). Scene change =
  restarts without smoothing (hard jump).
- **Split**: per scene, if ≥ 60% of the samples have the 2 main faces → top half = person on the left,
  bottom = person on the right (each half 1080×960, face at ~42% of the height); otherwise the scene uses the normal crop.
- **Manual**: `manual_crop_json` = `[{"t": relative_seconds, "x": normalized_center}]`, interpolated with smoothstep.
- **Render with variable crop**: ffmpeg decodes the source (`-ss` before `-i`, output `fps`) → Python
  crops each frame → a 2nd ffmpeg encodes (raw video via stdin + source audio + .ass + loudnorm).
  Without split, Python sends the crop at its native size (e.g. 404×720) and ffmpeg upscales it with lanczos. With split,
  it composes 1080×1920 in Python. `crop.json` saved per clip; `GET /clips/{id}/crop-track?fps=` for the editor.
- Source already vertical (≤ 9:16) → auto/split become center (nothing to reframe).
- Measured on the test podcast (8.5 min, 720p30, 108 camera cuts): full pipeline in 147 s; "follow face" render
  ~4–5 s per ~22 s clip, split ~9.5 s. Track: largest step ≤ 0.2% of the width per frame within a
  scene; exact jump on the cut frame.

## Phase 6 — Editor
- **Custom timeline (canvas + DOM) instead of wavesurfer.js.** We needed a ±30 s context window, an aligned
  thumbnail strip, handles that snap to words (Alt disables it), dragging the whole clip and a playhead without
  re-rendering — with wavesurfer that required syncing zoom/scroll of two components and fighting the
  Regions plugin. The waveform uses the precomputed peaks (`waveform.json`, 100/s). Ctrl+wheel = zoom, wheel = scroll.
- **9:16 preview on canvas**: a single `<video>` (the source's); the preview draws the crop every frame with
  `drawImage` (simple crop, split and blurred background), so it's always in sync. The auto/split track comes from
  `GET /clips/{id}/crop-track` (recomputed when the saved clip changes; the previous one stays on screen while loading).
  Manual is computed on the client (smoothstep, same as Python) — the dragged rectangle shows up instantly.
- **Preview captions** in HTML/CSS on a logical 1080×1920 layer, scaled, with the SAME fonts as the render
  (`/api/fonts`, served from `backend/assets/fonts`). The line/timing logic was ported to TS
  (`lib/captions.ts`) and both sides run the same cases (`backend/tests/fixtures/captions_cases.json`).
- **Font size**: ASS "Fontsize" isn't CSS font-size and the ratio depends on the family. MEASURED factor
  (height of "H" in libass ÷ in the browser): Montserrat 0.643, Inter 0.833, Bebas Neue 0.771 (`lib/fonts.ts`).
  Before the measurement the preview was 23% larger; afterwards, the preview and the MP4 frame are practically identical.
  Outline: `-webkit-text-stroke` at 2× the thickness + `paint-order: stroke fill` (ASS's is entirely outside).
- **Per-clip adjustments**: the clip points to a preset (`caption_style_id`) and stores adjustments in
  `caption_overrides_json.style`; the render applies preset + adjustments (`Style.merged`, with validation).
  "Save as new preset" creates a CaptionStyle and clears the adjustments. Choosing a preset clears the adjustments.
- `caption_overrides_json` = `{"words": {...}, "style": {...}, "title_until": 3}` (the old words-only format
  is still read). A word correction in the editor applies only to that clip's captions.
- **Export**: `Clip.export_json` = `{"quality": high|normal|small, "normalize_audio": bool}`. Quality →
  NVENC cq 19/21/25 (x264 crf 18/20/24) with a 12/8/4 Mbps cap.
- **State**: Zustand with a draft + undo stack (up to 200). Consecutive edits of the same control within < 1 s and
  gestures (dragging a handle/slider: `checkpoint()` at the start) become a single step. **Autosave**: diff of the draft vs.
  last saved, PATCH of only the changed fields, 800 ms debounce; Ctrl+S saves immediately; rendering saves first.
  The draft is loaded once per clip (later SSE events don't overwrite edits in progress).
- **Shortcuts**: Space, J (−2 s; HTML video doesn't play backwards reliably), K, L (2× if already
  playing), ←/→ (1 frame; Shift = 1 s), I/O, Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y too), Ctrl+S, Ctrl+Enter, ? = help.
  Playing from inside the clip stops at its end.
- **Shift+click** on the transcript: a word before the middle of the clip becomes the start; after it, the end (with breathing room).
- Tests: vitest (25: captions with shared cases, crop geometry, snapping, store/undo/diff) + pytest
  (64, incl. "edit in the editor → final MP4"). Acceptance also verified in the browser with Playwright (headless
  Chromium installed in `~/.cache/ms-playwright`, development only).

## Phase 7 — Polish
- **Installation for non-technical users**: `scripts/setup.sh` does everything in 5 steps. On Linux x86_64, whatever is missing is installed
  WITHOUT sudo in `~/.local` (uv, static BtbN FFmpeg with libass+NVENC, Node.js 22, Ollama); macOS/others get the
  exact instructions. Then: venv + deps, `npm ci && build`, `run.py --baixar-modelos` (Whisper according to the hardware +
  the Ollama model; on a machine without an 8 GB GPU it swaps the default 7b for the 3b and saves it in Settings) and
  `run.py --diagnostico`. `--sem-modelos` skips the ~8 GB of models.
- **Acceptance actually verified**: (A) clean copy of the project (no .venv/node_modules/dist/data) → `setup.sh` →
  `start.sh` on a separate port → real 8.5 min project analyzed (estimate 160 s, actual 150 s) and 3 clips
  rendered with "follow face"; (B) fake HOME and PATH without uv/ffmpeg → setup installed both by itself and the
  diagnostics were all green. Bugs found and fixed along the way: the libass check in the shell (FFmpeg 8's `-filters`
  has 2-character flags) and thumbnails (below).
- **Windows** (`setup.ps1` with winget, `start.bat`) and **macOS** (brew) — scripts written but NOT tested.
  `requirements.txt` uses a marker so the CUDA libs aren't installed on macOS; `run.py` puts the CUDA DLLs on the PATH on Windows.
- **Thumbnails**: `fps=1/10` generated nothing for videos < 10 s and FFmpeg 8's JPEG encoder rejects "limited
  range" YUV → now `select` (frame 0 and then every 10 s) + `out_range=full,format=yuvj420p`.
- **Per-file cache** in preparation: each step (audio, waveform, proxy, thumbnails) only runs if its
  file is missing; a changed source deletes all derivatives.
- **Storage** (Settings): usage per folder + cleanup of (1) temporaries/leftovers (`.part`, `.tmp`, folders of
  deleted projects/clips), (2) `audio.wav` of finished projects, (3) proxies of projects unused for N days
  (activity = last update of the project or one of its clips). Refuses to clean while a job is running (it would delete `.tmp` in use).
  Deleted proxy → project/editor show **"Prepare again"** (`probe_proxy` job with `Project.prepare_only`:
  restores only the files, without redoing transcription/AI).
- **Time estimate** (`GET /projects/{id}/estimate`): factors measured on this machine (large-v3 GPU transcription
  ~6.5× real time, preparation ~20× with NVENC, AI ~30 s per 8 min window); CPU with conservative factors; cached
  steps count as 0. Shown in the "Configure analysis" dialog.
- **Friendly errors** centralized in `app/errors.py` (GPU memory, CUDA, disk full, permission, missing
  file, unresponsive service); used in the Queue, project and clip, always with the technical details alongside.
- **Extra presets**: Impacto/Impact (Bebas Neue 1 word, red, pop), Minimal (Inter SemiBold, no highlight, bottom),
  Amarelo/Yellow (yellow text, white highlight). Added to existing databases on the next start.
- **Manual clip from scratch** opens straight in the editor. The default language in Settings applies to new projects.
- `run.py` warns in PT-BR if the port is already in use (and suggests `MDC_PORT`). Editor loaded on demand
  (main bundle < 500 kB).
- Complete Settings (§9.6): Whisper (model/device/precision), Ollama (address, installed model, Test),
  encoder, default language, export folder, audio normalization, yt-dlp, cookies and storage.

## Templates per content type (post-spec)
- `services/templates.py`: General, Gameplay, Podcast, Debate. Each defines framing, caption preset/position,
  extra AI prompt, volume cue and score weights. Chosen in "Configure analysis" (becomes the project
  default) and in **"Render all"** (`POST /projects/{id}/apply-template`, with `render: true`), which
  applies it to all active clips while preserving word/title corrections. A manual clip inherits the template.
- **Gameplay** (`reframe_mode="gameplay"`): webcam on top (40% of the height, adjustable 25–60%), game centered
  below. The facecam is detected as the face that stays in the same place for ≥ 25% of the video (fixed overlay).
  No stable facecam → whole game over a blurred background. In the editor you can drag the webcam and the game, change the
  zoom and the height (`Clip.layout_json`). Render with ffmpeg filters only (crop + vstack), no pipe through Python.
  AI: prompt for decisive plays/reactions; lines with a volume peak ≥ 1.6× the average arrive marked
  "[VOLUME ALTO]" (LOUD); score = 0.6 AI + 0.4 reaction heuristic (volume peaks), instead of speech pace.
  Captions on the webcam/game boundary (y = 0.4).
- **Podcast** (`reframe_mode="speaker"`): whoever is speaking in the center, switching with a hard cut (min. 1.5 s
  in frame; the other person must be clearly ahead for 0.8 s; only switches during speech).
  Who is speaking = **lip opening** (MediaPipe FaceLandmarker, points 13/14 ÷ 78/308), deviation over ~1 s:
  measured on the test podcast, the distribution is bimodal (silent ≤ 0.02; speaking 0.03–0.2). A person in profile
  (unreadable lips) is included by exclusion: there is voice and whoever is readable is silent → the unreadable one is speaking.
  Last resort (nobody readable): image diff of the mouth discounting the eyes/surrounding region, normalized.
  Attempts that did NOT work (recorded so they aren't repeated): image diff alone (hands gesturing near the
  mouth fool it — 2 of 8 wrong) and diarization via MFCC + k-means (56% purity ≈ chance).
  Visual check at 11 wide-shot moments of the test podcast: all plausibly correct.
  Cost: face analysis ~10 s per minute of video (was ~5.5), in parallel with transcription.
  `faces.json` v5 = [cx, cy, w, h, score, mouth_activity, frontality, lip_opening]; older versions are
  redone automatically. `mediapipe` came back to requirements just for this.
- **Debate**: the existing split screen (left on top, right below) + captions in the middle (y = 0.5) + prompt for
  confrontations/rebuttals.

## UI redesign (2026-11-24)

- **Identity**: neutral graphite base (doesn't tint the perception of the video's colors) + a single accent, caption yellow `#FFD23F` (taken from shorts captions). Coral `#FF5A4E` only for destructive/error. Tokens in `frontend/src/index.css`.
- **Typography**: variable Archivo (`@fontsource-variable/archivo`, bundled — the app is offline). Headings with the `font-display` utility (118% width, weight 800).
- **Home screen** (`/inicio`, new default route): a single "paste the link → Create clips" field that downloads with `send_to_project=true` (download → project → analysis on their own); playlists go to Downloads with `?links=` and are analyzed automatically; dragging/choosing a file uploads it and opens the project. Shows "In progress", "Continue editing" and "How it works".
- **Sidebar** in workflow order, with the running job visible (progress) and collapsed to icons inside the editor.
- **Assets** in `frontend/public/brand/` (SVG logo, illustrations, hero loop video) generated with Higgsfield (gpt_image_2_6 / seedance_2_5). The hero respects `prefers-reduced-motion`.

## Posting pack (roadmap #9, 2026-11-25)

- **`post_pack` job** (per clip, `ref_id` = clip; GPU slot because it uses Ollama). Options in `Job.params_json`
  (`{"texts": bool, "cover": bool}`, new column). Result in `Clip.post_json`: `tiktok {caption, hashtags}`,
  `reels {caption, hashtags}`, `shorts {title, description, hashtags}` + `cover_t`, `cover_at`, `model`.
  Generating/editing the pack does **not** change the clip status (the MP4 is still valid). Editing text = `PUT /clips/{id}/post`.
- **Texts**: the same model as the analysis (qwen2.5:7b), with its own JSON schema (`ollama_chat(schema=...)`); 1 retry
  at a lower temperature if the JSON is invalid. Normalization in the backend: limits (TikTok 300, Reels 600, Shorts
  title 100), hashtags without accents/spaces/duplicates (TikTok 5, Reels 8, Shorts 3 + `#Shorts` fixed in the final text).
  Measured on the GTA project (10 clips): ~20 s per clip including the cover. The 7B sometimes invents hashtags (e.g. "clonadore") —
  that's why everything is editable in the app.
- **Cover**: reuses the render plan (`render_plan`, extracted from `handle_render`): the frame comes out with the same
  framing as the MP4, but without captions. For face-following modes, it uses `reframer.frame_crop`; for
  filter-only modes (center, blurred, gameplay), it uses the `video_filter` without the `.ass`. 8 candidates (1 per segment of the clip, away from scene changes), each
  one with a face score from `faces.json` (size × confidence × frontal, penalizes a wide-open mouth, only faces inside
  the crop) and sharpness (Laplacian variance); score = 0.65 face + 0.35 sharpness (no faces: sharpness only).
  `cover-titulo.jpg` = same image + title (its own ASS, 120 px, bottom third).
- **Export**: `GET /projects/{id}/export.zip` builds the zip on the fly in `data/tmp/` (MP4/JPG uncompressed → 600 MB
  in ~3 s) and deletes it after sending. Only active clips with an MP4 are included; `textos.txt` says how many were left out.
  `textos.csv` has a UTF-8 BOM so Excel opens accents correctly.


## Claude as optional paid AI (roadmap #19 and #20, 2026-11-25)

- **Opt-in per action, never the default**: the analysis chooses `AnalysisOptions.llm` = `"ollama"` (default) or a Claude
  model id; the visual review has its own button. Without a key (Settings or `ANTHROPIC_API_KEY`), the API refuses with 409
  before enqueuing. The key lives in `data/settings.json` and `GET /system/settings` returns only `••••` + the last 4.
- **Cost before and after**: `services/claude.py` has the price table (US$/1M tokens, checked on 2026-11-03) and
  estimates the cost beforehand (`/projects/{id}/estimate` → `claude.models[]`; `/projects/{id}/review-estimate`). The UI shows the
  amount in the selector and on the button ("Analisar · ≈ US$ 0,73"). The actual cost comes from each response's `usage` (`CostMeter`) and
  is stored in `Project.ai_cost_json` (last analysis + sum of reviews + total) and in `Clip.review_json.cost`.
  Estimation heuristic: ~30 prompt characters per second of video (measured 19–23 in gameplay) ÷ 3 characters per
  token, + 2,500 reasoning tokens per call (`medium` effort); "worst case" = ×2 (retry due to invalid JSON).
  E.g.: 1 h of gameplay, 10 clips → Opus ≈ US$ 0.73, Sonnet ≈ 0.37, Haiku ≈ 0.02.
- **Same contract as Ollama**: `claude_chat` returns an `LLMCall` just like `ollama_chat`, so `find_highlights` didn't
  change. Output guaranteed by structured outputs (`output_config.format`) — the schema is converted (`strict_schema`:
  `additionalProperties: false`, no `minimum/maximum`; score clamping stays in the parse). Temperature is ignored
  (current models don't accept it). Streaming so it can be canceled. Opus/Sonnet with `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`) in case of refusal; Haiku doesn't have it.
- **Visual review** (`review` job, light slot — it's network, not GPU): 8 frames of the final MP4 (405×720, ≈390 tokens each) +
  the clip's speech → `{verdict ok|warn|bad, summary, issues[{t, kind, severity, text}]}`. Stores the `rendered_at` of the reviewed
  MP4: a re-render invalidates the badge (the UI warns). E.g.: Opus ≈ US$ 0.09 per clip, Sonnet ≈ 0.04, Haiku ≈ 0.002.
- The posting pack texts stay on Ollama (local).
- **Review through the Pro plan (no API key)**: the Pro subscription doesn't give API access and other apps can't use its
  login, so the review can also be done by Claude Code (the `/cortes` skill: `quadros <cid>` extracts the same
  8 frames + speech; `salvar-revisao` saves via `PUT /clips/{id}/review`). It gets `cost.provider = "claude-code"`,
  `usd = 0` and approximate plan usage in `tokens_approx`; it doesn't count toward `Project.ai_cost_json`.

## Other paid providers by key + OpenRouter (2026-11-25)

- **Model refs** (`services/ai.py`): Claude ids stay unprefixed (`claude-opus-5-5`, compatible with old
  data); the others are `<provider>:<id>` (`openrouter:openai/gpt-…`, `gemini:gemini-…`). `AnalysisOptions.llm`, the
  `review` job and `UserSettings.review_model` (new; migrated from `claude_model`) store the ref.
- **Providers**: Anthropic (SDK, `claude.py`) + OpenRouter, OpenAI, Google Gemini (compatibility endpoint),
  DeepSeek, xAI, Groq, Mistral and "custom" (any OpenAI-compatible base URL). All non-Anthropic ones go through
  a single client, `openai_compat.py`, using only `httpx` (no new dependency). Keys in `UserSettings.api_keys`
  (masked like Anthropic's) or in the provider's environment variable (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`…).
- **Adaptive parameters**: asks for `response_format: json_schema` (strict); if the provider refuses with 400/422, downgrades
  to `json_object` (with the schema in the prompt) and then to nothing; same for `temperature` and `stream_options`. A 400
  generates no tokens, so the retry doesn't charge twice. The response goes through `strip_fences` (```json, `<think>`).
- **Models and prices**: Claude's are built in. The user adds the others in Settings → Paid AI. On
  OpenRouter the public catalog (`/api/v1/models`, no key) has per-token prices and whether images are accepted; for the others the app
  lists the IDs via `GET /models` with the saved key and the price is typed in. No price: estimate and US$ cost are
  `null`/`priced: false` and the UI shows only the tokens.
- **Actual cost**: OpenRouter returns `usage.cost` (requested with `usage.include`), used as is; the others = `usage`
  tokens × configured price. If the provider doesn't send `usage`, tokens are estimated from the text (`approx: true`).
- **Testing a key is free** outside Claude: OpenRouter → `GET /key` (shows the remaining limit); others → `GET /models`.
- The visual review requires a model with vision (`vision`); images become `image_url` with a base64 data URL.
