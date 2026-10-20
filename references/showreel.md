# Showreel / 宣传片 from finished MVs

`scripts/promo_reel.py` + a JSON config (`examples/promo_config.json`). A four-MV reel runs about 60 s:
9.6 s montage + 3.2 s title + four 8–10 s highlights + 8 s pipeline card + 4 s end card.

## Workflow

1. **List the masters.** For each MV take the newest final render (not silent `_video` copies, not
   previews). Put them in `sources` as paths relative to `root`.
2. **Analyze.** `promo_reel.py analyze cfg.json` decodes each song at 4 kHz mono, scores 8 s windows by mean
   loudness + a bonus for a loudness jump (chorus / drop entries), keeps the top 3 non-overlapping windows,
   estimates BPM + first beat in each, and writes a 5×2 contact sheet (1 frame/s) per window.
3. **Pick by eye.** Loudness finds choruses but not the best pictures. From the sheets choose one window per
   MV with the character on-model and large, motion or a lyric slam, and no near-blank frames (paper
   layouts, text-only cards) or long static holds. Nudge `start` to where the action begins.
4. **Order calm → climax.** The montage at the top previews everything at high energy first.
5. **Montage.** One song carries the montage (`montage.audio`); shots are 2 beats then 1 beat each,
   accumulated on the frame grid so every cut lands on a beat; `flash: true` adds a white flash-in.
   Use shots *not* used in the highlights.
6. **Build.** `promo_reel.py build cfg.json` (add `--force` to redo all). Each highlight's start snaps to its
   next beat and its length rounds to whole beats; audio is gain-matched to `target_mean_db` (volumedetect)
   with a limiter, faded 30 ms in / 180 ms out, and each cut gets a 4-frame white flash-in.
7. **Check.** 1 fps sheet of the whole reel (`ffmpeg -vf fps=1,scale=320:180,tile=8x12`), EBU R128
   integrated loudness (~ −14 LUFS), and watch the joins.

## Config fields

| field | meaning |
|---|---|
| `root`, `work`, `out` | base folder (relative to the config), scratch folder (`PROMO_WORK` env overrides), output path relative to root |
| `fonts.display/serif/sans` | TTF/OTF paths; CJK needed (Noto Sans/Serif SC variable fonts work, weight via axis) |
| `accent` | RGB of numbers, lines, active pipeline step |
| `sources` | key → video path |
| `montage.audio` | `{src, start}`; first beat after `start` becomes the first cut |
| `montage.shots[]` | `{src, t, beats, flash?}` |
| `title` | `{beats, bg:{src,t}, lines:[kicker, headline, subline]}` (blurred, darkened bg) |
| `segments[]` | `{src, start, dur, title, sub, tag, snap?, cap_in?, cap_out?}`; tags split on " · " into chips |
| `pipeline` | `{heading, steps:[[name, detail]…], step_seconds, hold_seconds, bg?}`; audio = tail of the last segment's song |
| `end` | `{heading, items[], foot, seconds}`; empty `items` centres the heading |

## Lessons

- Blurred backgrounds behind cards must not contain big lyric typography: it reads through the blur.
  Pick a calm plate (`pipeline.bg`) and blur hard.
- Captions top-left: MVs usually put lyrics at the bottom or centre.
- Keep the caption on screen ~3.5 s, not the whole segment, so the last beats are clean picture.
- Songs in different keys: hard cuts with a white flash hide the key change better than crossfades.
- Don't state counts ("N works") in titles or captions unless asked; the reel should survive adding or
  removing a segment.
