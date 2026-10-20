"""Shot list = the single source of truth for one MV.  Copy into the project root and fill _S.

Each entry: (id, t0, keyframe scene, H3 motion prompt, flags).  t1 = next shot's t0, so shots tile the song.
t0 is in song seconds and is snapped to the nearest beat (within 0.22 s) from analysis/audio.json.

flags (combine freely):
  g  the character is in the shot (attach the character refs, add the identity lock)
  s  still: keyframe + code camera only, no H3 clip (face close-ups, title cards: H3 tends to morph faces)
  h  only hands / feet are shown          f  far: character is small in frame
  x  faceless shadow people               n  night grade          m  project-specific look (e.g. mono world)

Run:  python shots.py   -> data/shots.json + a table (id, t0, t1, length, flags) to sanity-check timing.
"""
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
_B = json.load(open(os.path.join(ROOT, "analysis/audio.json")))["beats"]   # from tools/analyze_audio.py
END = 0.0   # song length in seconds (set it)

_S = [
    # ---------------------------------------------------------------- INTRO
    ("I01", 0.00, "Wide establishing shot: <place, time of day, weather>. Nobody in the shot.",
     "Clouds drift slowly; light shifts. Static camera.", ""),
    ("I02", 3.70, "Medium shot: she <does something that states the theme>, <framing>, <light>.",
     "She <one clear motion>. Slow push-in.", "g"),
    ("I03", 7.40, "Extreme close-up of her eyes opening.", "", "gs"),
    # ---------------------------------------------------------------- VERSE 1 / CHORUS 1 ...
]


def _snap(t):
    if t <= 0.01:
        return 0.0
    c = min(_B, key=lambda b: abs(b - t))
    return round(c, 3) if abs(c - t) < 0.22 else round(t, 3)


_T = [_snap(s[1]) for s in _S] + [END]
SHOTS = [(s[0], _T[i], _T[i + 1], s[2], s[3], s[4]) for i, s in enumerate(_S)]

if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump([dict(id=a, t0=b, t1=c, flags=f, scene=d) for a, b, c, d, e, f in SHOTS],
              open(os.path.join(ROOT, "data/shots.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    for a, b, c, d, e, f in SHOTS:
        print(f"{a} {b:7.2f} {c:7.2f} {c - b:5.2f} {f}")
    print(len(SHOTS), "shots;", sum("s" not in s[5] for s in SHOTS), "H3 clips")
