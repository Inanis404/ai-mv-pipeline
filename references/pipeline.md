# The pipeline in detail

What each phase produces, how to check it, and the failures to plan for.

## Project layout

```
<Project>/
  audio/song.wav              the master audio (trim talking / silence before analysis)
  analysis/audio.json         beats, bars, sections, impacts
  analysis/lyrics_mv.lrc      timed lyrics (+ lyrics_src.txt with original / translation)
  docs/CONCEPT.md             thesis, motifs, palette arc, character notes
  ref/char_full.png ref/char_face.png   model sheet used by every keyframe job
  shots.py                    shot list (source of truth)  -> data/shots.json, STORYBOARD.md
  kf.py  h3_jobs.py  h3_i2v.py          generation drivers
  gen/kf/<id>.png             raw keyframes            clips/<id>.mp4   raw H3 clips (+ <id>_b.mp4 reruns)
  assets/kf/ assets/clips/    upscaled 1080p stills / frame sequences for the compositor
  engine/ or comp/            the edit                 render/          masters, share encodes, review sheets
```

## 1. Listen

- Beat grid, downbeats, bars, sections, loud impacts, an overview plot.
- Curate the automatic sections by ear (intro / verse / pre / chorus / bridge / outro).
- Note the stops (silence before a drop) and the impacts: these get the flashes, cuts and big type slams.
- **Check:** beat ticks line up with the kick; BPM is not half/double.

## 2. Lyrics

- Start from the official text, never from ASR. ASR is only for timing: Whisper / MMS forced alignment on
  the separated vocal, then reconcile line by line.
- One `.lrc` line per sung phrase, time = sung onset. Mark breaks, emphasis, slams and instrumental gaps.
- Bilingual output carries the translation as a second, smaller line.

## 3. Concept + storyboard

- A one-sentence thesis, 2–3 motifs that recur and escalate (a recurring pose, a gauge that climbs, an
  object that returns at the end), and a palette arc across the song (e.g. dusk → night → deep → pre-dawn → sun).
- Roughly one shot per lyric line (45–100 shots for a 3–5 min song); cuts on beats, big changes on downbeats.
- Write scene (what the still shows) and motion (what H3 should move) separately in `shots.py`.
- Flags drive prompt blocks: `g` character, `s` still, `h` hands only, `f` far, `x` shadow people, `n` night.

## 4. Keyframes

- Image model with reference images attached (Codex image gen via a jobs JSONL, or NovelAI with a fixed
  style string). Keep tokens / keys in a local secrets file that is never committed.
- Identity-lock paragraph in every `g` prompt (face shape, eye colour, eyelashes, ears/wings, hair, outfit).
- For shots without the character say so explicitly ("the girl does NOT appear") or she shows up anyway.
- Matched pairs (first/last frame for H3): generate the second as an *edit* of the first so the layout matches.
- **Check:** one contact sheet of all keyframes; fix off-model faces, extra people, text/watermarks, wrong
  ears before spending GPU on video.

## 5. Image-to-video (MiniMax H3, local ComfyUI)

- `h3_i2v.py --first kf.png [--last kf2.png] [--mid img@0.5] --prompt … --frames N --out clips/ID.mp4`.
- Length is snapped to 17k+5 frames at 24 fps; per shot = shot length + 0.3 s, min 49, max 121 frames.
- Motion prompt = motion + identity lock + camera lock (one continuous take, no cut, no close-up, no zoom
  into a face) + "Smooth, strong, dynamic motion." The negative block forbids text, morphing faces,
  extra characters.
- `--control ctrl.mp4` switches to reference-to-video + Fun ControlNet (pose / depth / line video) with the
  4-step turbo LoRA, for choreography (dance loops, specific gestures).
- Seed = hash of shot id, so reruns are reproducible; QA failures go to `RERUN` with a stricter prompt and
  render to `<id>_b.mp4`.
- **Typical failures:** face morph on push-ins (→ make it a still), she turns around (→ "keeps the same
  facing direction"), a second character appears (→ "only one girl in the whole clip"), sudden cut mid-clip
  (→ camera lock), cloth/veil does something it shouldn't (→ state what never happens).

## 6. Upscale + prep

- Keyframes: Real-ESRGAN x4plus-anime ×4 → Lanczos cover-crop 1920×1080.
- Clips: frames → realesr-animevideov3 ×2 → 16:9 crop → 1080p JPEG sequence (`prep_clip.py`).
- `--fast` = Lanczos only, with a marker so the next full pass redoes them.

## 7. Composite

Two kinds of compositor work:

- **Code engine:** the edit is a timeline file; Canvas2D scenes + a hand-lettered lyric layer + foreground +
  WebGL post, rendered headless (Playwright) and encoded by ffmpeg. Deterministic: same code, same frames.
  Code-drawn plates (counters, gauges, UI cards, equations) are cheaper and sharper than generating them.
- **ffmpeg comp:** a shot plan JSON + per-shot overrides (zoom in/out, pan, use part of a clip, flash /
  dissolve transitions, particle overlays like snow, wind, shake) and a grade chosen by song time.

Either way: cuts on beats, flashes on impacts, lyric typography timed to sung onsets, grade follows the
palette arc, stills get a slow code camera (1.00 → 1.06 zoom).

## 8. Review → deliver

- Stills at chosen times → contact sheet; full render → 1 s review sheets, 2–3 passes.
- Look for: lyrics over faces, off-model frames, flicker at clip joins, dead air on stops, text legibility
  on bright plates.
- Deliver: 16:9 master (CRF ~14–16), share encode, 720p preview, optional 9:16 vertical.

## Tooling notes

- Machine-specific paths come from env: `COMFY_ROOT`, `COMFY_URL`, `ESRGAN`, `FFMPEG`, `CODEX_BIN`.
- One Python venv (numpy, Pillow, faster-whisper); Node + Playwright for a code engine.
