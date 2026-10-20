"""MiniMax H3 clips for every non-still shot in shots.py -> clips/<id>.mp4

usage: python h3_jobs.py [--only C07,C08] [--force] [--rerun]
  --rerun  re-generate the shots listed in RERUN (QA failures) with a stricter motion prompt and a new seed
           -> clips/<id>_b.mp4 (keep both; pick in review)

Clip length = shot length + 0.3 s at 24 fps (min 49, max 121 frames; longer shots are slowed or held in the
compositor). Seeds are derived from the shot id so a re-run of the same shot is reproducible.
"""
import argparse, math, os, subprocess, sys, time
from shots import SHOTS

ROOT = os.path.dirname(os.path.abspath(__file__))
H3 = os.path.join(ROOT, "h3_i2v.py")   # copy scripts/h3_i2v.py from the skill repo next to this file

# identity + camera locks appended to every motion prompt (edit per character)
GIRL = (" Keep her exact face, eyes, hair, accessories and outfit from the first frame; only one girl in the whole clip,"
        " no new accessories. She keeps the same distance from the camera and the same facing direction;"
        " the camera never moves in to her face.")
HAND = " Only her hand / feet stay in frame; no face appears."
SHADOW = " The figures stay faceless black shadows the whole time; no faces appear."
EMPTY = " Nobody appears at any time: no people, no faces; only the scenery, light and objects move."
CALM = (" One continuous take: the framing stays as wide as the first frame until the end, same location and lighting,"
        " no scene cut, no close-up, no zoom into a face.")
RERUN = {
    # "P04": "stricter motion prompt for a shot that failed QA",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--force", action="store_true"); ap.add_argument("--rerun", action="store_true")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    for sid, t0, t1, scene, motion, flags in SHOTS:
        if (only and sid not in only) or "s" in flags or (a.rerun and sid not in RERUN):
            continue
        kf = os.path.join(ROOT, "gen/kf", sid + ".png")
        out = os.path.join(ROOT, "clips", sid + ("_b" if a.rerun else "") + ".mp4")
        if sid in RERUN:
            motion = RERUN[sid]
        if not os.path.exists(kf):
            print("no keyframe", sid); continue
        if os.path.exists(out) and not a.force:
            continue
        frames = min(121, max(49, math.ceil((t1 - t0 + 0.3) * 24)))
        lock = HAND if "h" in flags else GIRL if "g" in flags else (EMPTY if "x" not in flags else "")
        prompt = motion + lock + (SHADOW if "x" in flags else "") + CALM + " Smooth, strong, dynamic motion."
        seed = (sum(map(ord, sid)) * 7919 + (31 if a.rerun else 0)) % 100000
        t = time.time()
        r = subprocess.run([sys.executable, H3, "--first", kf, "--prompt", prompt, "--frames", str(frames),
                            "--out", out, "--seed", str(seed)])
        print(sid, "ok" if r.returncode == 0 else "FAILED", f"{time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
