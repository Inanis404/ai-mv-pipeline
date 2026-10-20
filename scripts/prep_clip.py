"""H3 clip -> crisp 1920x1080 JPEG frame sequence for the code compositor.

mp4 (e.g. 1344x768 @ 24 fps) -> PNG frames -> Real-ESRGAN realesr-animevideov3 x2 (Vulkan GPU)
-> centre-crop to 16:9 -> Lanczos 1920x1080 -> assets/clips/<name>/0001.jpg ...

usage: python prep_clip.py [--fast] clips/S08.mp4 [more.mp4 ...]
  --fast  Lanczos only, no GPU (previews while H3 is still running); leaves a .fast marker so a later
          full pass redoes the clip.
Env: FFMPEG (default: ffmpeg on PATH), ESRGAN (path to realesrgan-ncnn-vulkan executable), PROJECT (default: cwd).
"""
import os, shutil, subprocess, sys, tempfile
from PIL import Image

ROOT = os.environ.get("PROJECT", os.getcwd())
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
ESR = os.environ.get("ESRGAN", "realesrgan-ncnn-vulkan")


def prep(src, fast=False):
    name = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(ROOT, "assets", "clips", name)
    os.makedirs(os.path.join(ROOT, "gen"), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="h3_", dir=os.path.join(ROOT, "gen"))
    raw, up = os.path.join(tmp, "raw"), os.path.join(tmp, "up")
    os.makedirs(raw); os.makedirs(up)
    subprocess.run([FFMPEG, "-v", "error", "-i", src, os.path.join(raw, "%04d.png")], check=True)
    if fast:
        up = raw
    else:
        esr_dir = os.path.dirname(shutil.which(ESR) or ESR) or None
        subprocess.run([ESR, "-i", raw, "-o", up, "-n", "realesr-animevideov3", "-s", "2", "-f", "png"],
                       check=True, cwd=esr_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    files = sorted(os.listdir(up))
    for f in files:
        im = Image.open(os.path.join(up, f)).convert("RGB")
        w, h = im.size
        ch = round(w * 9 / 16)
        y0 = (h - ch) // 2
        im.crop((0, y0, w, y0 + ch)).resize((1920, 1080), Image.LANCZOS).save(
            os.path.join(out, f.replace(".png", ".jpg")), quality=92)
    if fast:
        open(os.path.join(out, ".fast"), "w").close()
    shutil.rmtree(tmp)
    print(name, len(files), "frames", "(fast)" if fast else "")


if __name__ == "__main__":
    fast = "--fast" in sys.argv
    for s in [a for a in sys.argv[1:] if a != "--fast"]:
        prep(s, fast)
