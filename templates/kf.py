"""Keyframes for every shot in shots.py -> gen/kf/<id>.png.

usage: python kf.py [--only P02,C10] [--force] [--conc 8] [--tag kf]

Writes a jobs JSONL and hands it to tools/imagegen.py (a Codex CLI image-generation wrapper). Every job
attaches the character reference images, so the character stays on-model across ~50-100 shots. To use NovelAI instead, write the same prompts into a specs JSON for nai.py
(see references/pipeline.md §4).

Edit CHAR / STYLE / REFS for the project; the flag blocks mirror the flags in shots.py.
"""
import argparse, json, subprocess, sys
from shots import SHOTS

REFS = ["ref/char_full.png", "ref/char_face.png"]          # model sheet: full body + face close-up
CHAR = "<one paragraph: face, eyes, hair, ears/accessories, outfit, colours — the identity lock>"
STYLE = ("Premium modern anime key visual, clean cel shading, crisp lineart, cinematic lighting, 16:9, "
         "no text, no watermark, no logo.")

SAME = ("The girl is the same character as in the reference images (full body + face close-up): keep her face, eyes, "
        "hair, accessories, outfit and colours exactly. Show her only once, in the pose the scene describes. ")
NOGIRL = "Use the reference images only for the art style; the girl does NOT appear in this shot. "
FLAG_TEXT = {
    "h": " Show only the part of her body the scene describes (hands / feet), matching her outfit.",
    "f": " She is small in the frame; keep her silhouette readable.",
    "x": " Other people are faceless black shadows or silhouettes: no faces, no features.",
    "n": " Night: deep blue darkness with strong rim light and reflections.",
}


def prompt(scene, flags):
    p = (SAME if "g" in flags else NOGIRL) + "Scene: " + scene + " "
    if "g" in flags and "h" not in flags:
        p += "The girl: " + CHAR + ". "
    for k, t in FLAG_TEXT.items():
        if k in flags:
            p += t
    return p + " " + STYLE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--conc", default="8"); ap.add_argument("--tag", default="kf")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    jf = f"gen/jobs_{a.tag}.jsonl"
    with open(jf, "w", encoding="utf-8") as f:
        for sid, t0, t1, scene, motion, flags in SHOTS:
            if only and sid not in only:
                continue
            f.write(json.dumps({"id": sid, "out": f"gen/{a.tag}/{sid}.png", "transparent": False,
                                "images": REFS, "prompt": prompt(scene, flags)}, ensure_ascii=False) + "\n")
    cmd = [sys.executable, "tools/imagegen.py", jf, "--out-dir", ".", "--concurrency", a.conc]
    if a.force:
        cmd.append("--force")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
