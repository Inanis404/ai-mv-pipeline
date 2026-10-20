---
name: ai-mv-pipeline
description: Turn a song into an anime-style lyric MV/PV with an AI pipeline (beat analysis, lyric alignment, shot list, character-locked keyframes, MiniMax H3 image-to-video, code compositing, review), and cut a beat-synced showreel from finished MVs. Use for "make an MV/PV for this song", "AI 出 MV", or "混剪宣传片 / showreel of our MVs".
---

# AI MV pipeline

One song in, one finished MV out, every step scripted so any shot can be regenerated and the whole film
re-rendered. Two jobs live here:

1. **Make an MV**: phases 0–8 below; details and lessons in `references/pipeline.md`.
2. **Cut a showreel / 宣传片 from finished MVs**: `scripts/promo_reel.py`; how-to in `references/showreel.md`.

## Ground rules

- **The shot list is the source of truth.** `shots.py` holds `(id, t0, scene, motion, flags)` for every shot,
  t0 snapped to the beat grid. Keyframes, H3 jobs, the compositor and the storyboard all read it. Change a
  shot there, then regenerate only that id (`--only S12`).
- **Character lock everywhere.** Every keyframe job attaches the model sheet (full body + face). Every H3
  prompt ends with the identity lock + camera lock (no zoom into faces, no cuts, no new accessories).
- **Close-ups are stills** (`s` flag): keyframe + code camera move. H3 morphs faces; don't animate them.
- **Generate in batches, review in sheets.** Never judge a clip alone: contact sheets of keyframes,
  1 fps review sheets of renders, then re-run only failures (`--rerun` → `<id>_b.mp4`, keep both).
- **Everything resumable.** Each script skips outputs that exist; `--force` redoes. Long renders write to a
  temp name and rename at the end, so a killed run never leaves a half file that looks finished.
- **Previews first.** `--fast` paths (Lanczos instead of ESRGAN) let the edit move while the GPU is busy.

## Phases (make an MV)

| # | phase | output | tool |
|---|---|---|---|
| 0 | Scaffold | project folder, `audio/song.wav` | copy `templates/` into a new folder |
| 1 | Listen | `analysis/audio.json` (beats, bars, sections, impacts), `overview.png` | audio analysis script; curate `sections.json` |
| 2 | Lyrics | `analysis/lyrics_mv.lrc` with sung-onset times (+ translation line) | official text + Whisper / MMS alignment for timing only |
| 3 | Concept + storyboard | `docs/CONCEPT.md`, `shots.py` → `STORYBOARD.md` | one thesis, 2–3 motifs, a palette arc; ~1 shot per lyric line |
| 4 | Keyframes | `gen/kf/<id>.png` | `templates/kf.py` → image model (Codex image gen or NovelAI) with refs |
| 5 | Image-to-video | `clips/<id>.mp4` | `templates/h3_jobs.py` → `scripts/h3_i2v.py` (MiniMax H3 in local ComfyUI) |
| 6 | Upscale + prep | `assets/kf/*.jpg`, `assets/clips/<id>/*.jpg` | `scripts/prep_clip.py` (Real-ESRGAN anime) |
| 7 | Composite | code timeline or ffmpeg comp | lyric typography layer, WebGL / ffmpeg post, grades, transitions on beats |
| 8 | Review → deliver | review sheets, master, share encode, 9:16 | 1 fps review sheets, final render |

Phase acceptance checks, prompt blocks and failure fixes: `references/pipeline.md`.

## Showreel (混剪宣传片)

```bash
python scripts/promo_reel.py analyze promo_config.json   # loudest windows + BPM + contact sheets per MV
# look at the sheets, pick one highlight per MV, write the times into the config
python scripts/promo_reel.py build   promo_config.json   # -> reel + 720p share copy (resumable)
```

Structure: beat-synced flash montage on one song → title card → one 8–10 s highlight per MV with its own
audio and a caption card (title · subtitle · pipeline tags) → "how it's made" pipeline card → end card.
Start from `examples/promo_config.json`. Order highlights calm → climax.

## When the shell is a remote VM

Background jobs may die when the call returns and calls can be capped at a few minutes: run `build`
repeatedly (it resumes), and keep scratch (`PROMO_WORK=...`) outside folders where deleting needs permission.
