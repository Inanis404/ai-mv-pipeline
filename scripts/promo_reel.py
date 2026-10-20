#!/usr/bin/env python3
"""promo_reel.py — cut a showcase / sizzle reel out of finished AI-pipeline MVs.

Two sub-commands, both driven by one JSON config (see examples/promo_config.json):

  python promo_reel.py analyze  config.json   # loudest windows + BPM per source -> <work>/candidates.json + contact sheets
  python promo_reel.py build    config.json   # render the reel -> config["out"]  (resumable; add --force to redo all)

Reel structure (every part optional except segments):
  montage   beat-synced flash cuts from all sources, over one song's audio
  title     title card on a blurred frame, still on the montage audio
  segments  one highlight per MV with its own audio, a white flash-in on the cut and a top-left caption card
  pipeline  "how it was made" card, steps lighting up one by one, over the tail of the last segment's song
  end       end card (titles list / credit), fades to black

Requirements: ffmpeg + ffprobe on PATH (4.4+), Python 3.9+, numpy, Pillow.
"""
import json, math, os, subprocess, sys, shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SR = 4000  # analysis sample rate (mono); plenty for loudness + kick/snare onsets


# ----------------------------------------------------------------------------- helpers
def run(cmd, quiet=True):
    """Run a command. If the last argument is an output .mp4 Path, write to <name>.part.mp4 and rename on success,
    so an interrupted build never leaves a half-written piece that a resumed build would trust."""
    cmd = list(cmd)
    final = cmd[-1] if isinstance(cmd[-1], Path) and cmd[-1].suffix == ".mp4" else None
    if final is not None:
        cmd[-1] = final.with_name(final.stem + ".part.mp4")
    if not quiet:
        print(" ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"command failed: {cmd[:6]}…")
    if final is not None:
        os.replace(cmd[-1], final)
    return r


FORCE = "--force" in sys.argv


def cached(out):
    """True when a finished piece already exists (resume support; --force rebuilds everything)."""
    return (not FORCE) and Path(out).exists() and Path(out).stat().st_size > 0


def ffprobe_dur(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(r.stdout.strip())


def load_pcm(src, cache):
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / (Path(src).stem + ".pcm")
    if not p.exists():
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", SR, "-f", "f32le", p])
    return np.fromfile(p, dtype=np.float32)


def onset_env(x, hop=40, n=256):
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    S = np.log1p(10 * np.abs(np.fft.rfft(fr, axis=1)))
    f = np.concatenate([[0], np.maximum(0, np.diff(S, axis=0)).sum(1)])
    f -= np.convolve(f, np.ones(15) / 15, "same")
    return np.maximum(f, 0), SR / hop


def beat_grid(x, t0, dur, bpm_range=(70, 200)):
    """Return (bpm, period_s, first_beat_offset_s) for x[t0:t0+dur] via onset autocorrelation."""
    seg = x[int(t0 * SR): int((t0 + dur) * SR)]
    o, fps = onset_env(seg)
    ac = np.correlate(o, o, "full")[len(o) - 1:]
    lo, hi = int(fps * 60 / bpm_range[1]), int(fps * 60 / bpm_range[0])
    lag = lo + int(np.argmax(ac[lo:hi]))
    phase = max(range(lag), key=lambda p: o[p::lag].sum())
    return 60 * fps / lag, lag / fps, phase / fps


def loud_windows(x, win, k=3, edge=(0.08, 0.92)):
    """Top-k non-overlapping windows by mean loudness + bonus for a jump in (chorus / drop entries)."""
    hop = SR // 4
    n = len(x) // hop
    r = np.sqrt(np.array([np.mean(x[i * hop:(i + 1) * hop] ** 2) for i in range(n)]) + 1e-9)
    db = 20 * np.log10(r)
    W = int(win * 4)
    cands = []
    for s in range(int(edge[0] * n), int(edge[1] * n) - W):
        m = db[s:s + W].mean()
        pre = db[max(0, s - 12):s].mean() if s > 12 else m
        cands.append((m + 0.6 * float(np.clip(db[s:s + 4].mean() - pre, 0, 8)), s / 4))
    cands.sort(reverse=True)
    picks = []
    for sc, t in cands:
        if all(abs(t - p) > win * 1.5 for _, p in picks):
            picks.append((sc, t))
        if len(picks) == k:
            break
    return [(round(t, 2), round(float(sc), 2)) for sc, t in picks]


def mean_volume(src, start, dur):
    r = subprocess.run(["ffmpeg", "-nostdin", "-ss", str(start), "-t", str(dur), "-i", src, "-vn",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split(":")[1].split()[0])
    return -20.0


# ----------------------------------------------------------------------------- typography
class Fonts:
    def __init__(self, cfg, root):
        self.cfg = {k: str((root / v) if not os.path.isabs(v) else v) for k, v in cfg.items()}

    def get(self, role, size, weight=None):
        f = ImageFont.truetype(self.cfg[role], size)
        if weight:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        return f


def text_w(draw, s, font, spacing=0):
    if not s:
        return 0
    return draw.textlength(s, font=font) + spacing * (len(s) - 1)


def draw_spaced(draw, xy, s, font, fill, spacing=0):
    x, y = xy
    for ch in s:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x


def caption_png(path, W, H, F, idx, total, title, sub, tag, accent):
    """Top-left caption card: index, title, subtitle (artist / song), pipeline tag line."""
    S = W / 1920
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # soft dark vignette top-left for legibility
    g = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(g)
    gd.ellipse((-int(700 * S), -int(500 * S), int(1100 * S), int(560 * S)), fill=150)
    g = g.filter(ImageFilter.GaussianBlur(int(120 * S)))
    im.paste(Image.new("RGBA", (W, H), (6, 8, 16, 255)), (0, 0), g)
    d = ImageDraw.Draw(im)
    x0, y0 = int(84 * S), int(70 * S)
    fi = F.get("display", int(30 * S))
    d.text((x0, y0), f"{idx:02d}", font=fi, fill=accent)
    d.line((x0, y0 + int(52 * S), x0 + int(56 * S), y0 + int(52 * S)), fill=accent, width=max(2, int(3 * S)))
    ft = F.get("serif", int(68 * S), 800)
    d.text((x0 - 2, y0 + int(66 * S)), title, font=ft, fill=(255, 255, 255, 255),
           stroke_width=max(1, int(1 * S)), stroke_fill=(0, 0, 0, 90))
    y = y0 + int(66 * S) + int(92 * S)
    if sub:
        d.text((x0, y), sub, font=F.get("sans", int(26 * S), 500), fill=(255, 255, 255, 215))
        y += int(44 * S)
    if tag:
        ftag = F.get("sans", int(22 * S), 600)
        for i, t in enumerate(tag.split(" · ")):
            tw = d.textlength(t, font=ftag)
            pad = int(12 * S)
            d.rounded_rectangle((x0, y, x0 + tw + 2 * pad, y + int(36 * S)), radius=int(6 * S),
                                fill=(255, 255, 255, 28), outline=accent[:3] + (200,), width=1)
            d.text((x0 + pad, y + int(5 * S)), t, font=ftag, fill=(255, 255, 255, 235))
            x0 += tw + 2 * pad + int(10 * S)
    im.save(path)


def title_png(path, W, H, F, lines, accent):
    S = W / 1920
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    kicker, head, sub = (lines + ["", "", ""])[:3]
    fk = F.get("sans", int(28 * S), 600)
    fh = F.get("serif", int(118 * S), 900)
    fs = F.get("sans", int(34 * S), 400)
    cy = H // 2
    if kicker:
        sp = int(10 * S)
        w = text_w(d, kicker, fk, sp)
        draw_spaced(d, ((W - w) / 2, cy - int(150 * S)), kicker, fk, accent, sp)
    w = d.textlength(head, font=fh)
    d.text(((W - w) / 2, cy - int(92 * S)), head, font=fh, fill=(255, 255, 255, 255))
    d.line((W / 2 - int(60 * S), cy + int(84 * S), W / 2 + int(60 * S), cy + int(84 * S)), fill=accent, width=max(2, int(3 * S)))
    if sub:
        w = d.textlength(sub, font=fs)
        d.text(((W - w) / 2, cy + int(108 * S)), sub, font=fs, fill=(255, 255, 255, 220))
    im.save(path)


def pipeline_pngs(prefix, W, H, F, heading, steps, accent):
    """One PNG per state: step i lit (accent), earlier steps done (white), later steps dim."""
    S = W / 1920
    n = len(steps)
    paths = []
    cols = min(n, 4)
    rows = math.ceil(n / cols)
    bw, bh, gx, gy = int(360 * S), int(150 * S), int(56 * S), int(70 * S)
    tw = cols * bw + (cols - 1) * gx
    th = rows * bh + (rows - 1) * gy
    ox, oy = (W - tw) // 2, (H - th) // 2 + int(50 * S)
    for k in range(n + 1):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        fh = F.get("serif", int(56 * S), 800)
        w = d.textlength(heading, font=fh)
        d.text(((W - w) / 2, oy - int(150 * S)), heading, font=fh, fill=(255, 255, 255, 255))
        for i, (name, detail) in enumerate(steps):
            r, c = divmod(i, cols)
            if r % 2 == 1:
                c = cols - 1 - c  # snake order so arrows stay short
            x, y = ox + c * (bw + gx), oy + r * (bh + gy)
            state = "on" if i == k else ("done" if i < k or k == n else "off")
            border = accent if state == "on" else ((255, 255, 255, 200) if state == "done" else (255, 255, 255, 60))
            fill = accent[:3] + (60,) if state == "on" else ((255, 255, 255, 22) if state == "done" else (255, 255, 255, 8))
            d.rounded_rectangle((x, y, x + bw, y + bh), radius=int(14 * S), fill=fill, outline=border, width=max(2, int(2 * S)))
            alpha = 255 if state != "off" else 90
            d.text((x + int(22 * S), y + int(18 * S)), f"{i + 1:02d}", font=F.get("display", int(24 * S)),
                   fill=accent[:3] + (alpha,))
            d.text((x + int(22 * S), y + int(50 * S)), name, font=F.get("sans", int(34 * S), 800), fill=(255, 255, 255, alpha))
            d.text((x + int(22 * S), y + int(100 * S)), detail, font=F.get("sans", int(20 * S), 400),
                   fill=(255, 255, 255, int(alpha * 0.8)))
            if i < n - 1:  # connector
                r2, c2 = divmod(i + 1, cols)
                if r2 % 2 == 1:
                    c2 = cols - 1 - c2
                x2, y2 = ox + c2 * (bw + gx), oy + r2 * (bh + gy)
                col = (255, 255, 255, 160 if i < k else 50)
                if r2 == r:
                    a, b = (x + bw, y + bh // 2), (x2, y2 + bh // 2)
                    if c2 < c:
                        a, b = (x, y + bh // 2), (x2 + bw, y2 + bh // 2)
                else:
                    a, b = (x + bw // 2, y + bh), (x2 + bw // 2, y2)
                d.line((a, b), fill=col, width=max(2, int(2 * S)))
        p = f"{prefix}_{k:02d}.png"
        im.save(p)
        paths.append(p)
    return paths


def end_png(path, W, H, F, head, items, foot, accent):
    S = W / 1920
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fh = F.get("serif", int(72 * S), 900)
    w = d.textlength(head, font=fh)
    y = int(230 * S) if items else H // 2 - int(70 * S)
    d.text(((W - w) / 2, y), head, font=fh, fill=(255, 255, 255, 255))
    y += int(180 * S)
    fi = F.get("sans", int(30 * S), 500)
    cols = 2
    colw = int(620 * S)
    x0 = (W - cols * colw) // 2
    for i, it in enumerate(items):
        c, r = i % cols, i // cols
        xx, yy = x0 + c * colw, y + r * int(66 * S)
        d.text((xx, yy), f"{i + 1:02d}", font=F.get("display", int(24 * S)), fill=accent)
        d.text((xx + int(56 * S), yy - int(4 * S)), it, font=fi, fill=(255, 255, 255, 230))
    if foot:
        ff = F.get("sans", int(24 * S), 400)
        w = d.textlength(foot, font=ff)
        d.text(((W - w) / 2, H - int(150 * S)), foot, font=ff, fill=(255, 255, 255, 170))
    im.save(path)


# ----------------------------------------------------------------------------- render pieces
class Reel:
    def __init__(self, cfg_path):
        self.cfg_path = Path(cfg_path).resolve()
        self.c = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        c = self.c
        base = self.cfg_path.parent
        self.root = (base / c.get("root", ".")).resolve()
        self.work = Path(os.environ.get("PROMO_WORK") or (base / c.get("work", "_work"))).resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.W, self.H, self.fps = c.get("width", 1920), c.get("height", 1080), c.get("fps", 30)
        self.F = Fonts(c["fonts"], self.root)
        self.accent = tuple(c.get("accent", [255, 196, 92])) + (255,)
        self.src = {k: str(self.root / v) for k, v in c["sources"].items()}
        self.venc = ["-c:v", "libx264", "-preset", c.get("preset", "veryfast"), "-crf", str(c.get("crf", 18)),
                     "-pix_fmt", "yuv420p", "-r", str(self.fps)]
        self.aenc = ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]
        self.target_db = c.get("target_mean_db", -17.0)

    def vnorm(self):
        return (f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H},"
                f"fps={self.fps},setsar=1,format=yuv420p")

    def frames(self, d):
        return max(1, round(d * self.fps))

    # -- analysis ------------------------------------------------------------------------
    def analyze(self):
        out = {}
        win = self.c.get("segment_seconds", 8)
        sheets = self.work / "sheets"
        sheets.mkdir(exist_ok=True)
        for k, s in self.src.items():
            x = load_pcm(s, self.work / "pcm")
            wins = loud_windows(x, win)
            info = {"duration": round(len(x) / SR, 2), "windows": []}
            for t, sc in wins:
                bpm, per, ph = beat_grid(x, t, win + 2)
                sheet = sheets / f"{k}_{t:.1f}.jpg"
                run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", t, "-i", s, "-t", win + 2,
                     "-vf", "fps=1,scale=320:180,tile=5x2", "-frames:v", 1, sheet])
                info["windows"].append({"start": t, "score": sc, "bpm": round(bpm, 1),
                                        "first_beat": round(t + ph, 3), "sheet": str(sheet)})
            out[k] = info
            print(k, [(w["start"], w["bpm"]) for w in info["windows"]])
        p = self.work / "candidates.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("->", p)

    # -- pieces ----------------------------------------------------------------------------
    def snap(self, key, start, dur):
        """Move start onto the nearest following beat and round dur to whole beats."""
        x = load_pcm(self.src[key], self.work / "pcm")
        bpm, per, ph = beat_grid(x, start, dur + 2)
        beats = max(1, round(dur / per))
        return start + ph, beats * per, bpm

    def montage(self):
        m = self.c["montage"]
        akey, astart = m["audio"]["src"], m["audio"]["start"]
        x = load_pcm(self.src[akey], self.work / "pcm")
        bpm, per, ph = beat_grid(x, astart, 12)
        if m.get("bpm"):
            per = 60 / m["bpm"]
        a0 = astart + ph
        parts, t = [], 0.0
        for i, sh in enumerate(m["shots"]):
            d = sh.get("beats", 1) * per
            fr = self.frames(t + d) - self.frames(t)  # accumulate on the frame grid so cuts stay on beat
            out = self.work / f"m_{i:02d}.mp4"
            if cached(out):
                parts.append(out); t += d; continue
            run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", sh["t"], "-i", self.src[sh["src"]],
                 "-vf", self.vnorm() + (",fade=in:0:2:color=white" if sh.get("flash") else ""),
                 "-frames:v", fr, "-an", *self.venc, out])
            parts.append(out)
            t += d
        print(f"montage: {len(parts)} shots, {bpm:.1f} BPM, {t:.2f}s")
        return parts, a0, t, per

    def title_card(self, a_len_beats, per):
        tc = self.c["title"]
        d = a_len_beats * per
        png = self.work / "title.png"
        title_png(png, self.W, self.H, self.F, tc["lines"], self.accent)
        bg = tc.get("bg")
        out = self.work / "title.mp4"
        fr = self.frames(d)
        if cached(out):
            return out, d
        if bg:
            src = ["-ss", bg["t"], "-i", self.src[bg["src"]]]
            vf_bg = (f"[0:v]{self.vnorm()},boxblur=24:2,eq=brightness=-0.28:saturation=0.7[b]")
        else:
            src = ["-f", "lavfi", "-i", f"color=c=0x07080f:s={self.W}x{self.H}:r={self.fps}"]
            vf_bg = "[0:v]format=yuv420p[b]"
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", *src, "-loop", 1, "-i", png, "-filter_complex",
             f"{vf_bg};[1:v]format=rgba,fade=in:st=0:d=0.25:alpha=1[o];[b][o]overlay=0:0:shortest=1,"
             f"fade=in:0:3:color=white,fade=out:st={d - 0.12:.3f}:d=0.12:color=white[v]",
             "-map", "[v]", "-frames:v", fr, "-an", *self.venc, out])
        return out, d

    def segment(self, i, s, total):
        key = s["src"]
        start, dur = s["start"], s["dur"]
        if s.get("snap", True):
            start, dur, _ = self.snap(key, start, dur)
        png = self.work / f"cap_{i:02d}.png"
        caption_png(png, self.W, self.H, self.F, i + 1, total, s["title"], s.get("sub", ""), s.get("tag", ""), self.accent)
        fr = self.frames(dur)
        dur = fr / self.fps
        out = self.work / f"seg_{i:02d}.mp4"
        if cached(out):
            print(f"segment {i + 1}: cached")
            return out, key, start + dur
        gain = self.target_db - mean_volume(self.src[key], start, dur)
        cap_in, cap_out = s.get("cap_in", 0.35), min(s.get("cap_out", 3.6), dur - 0.6)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", start, "-i", self.src[key], "-loop", 1, "-i", png,
             "-filter_complex",
             f"[0:v]{self.vnorm()},fade=in:0:4:color=white[b];"
             f"[1:v]format=rgba,fade=in:st={cap_in}:d=0.35:alpha=1,fade=out:st={cap_out}:d=0.5:alpha=1[o];"
             f"[b][o]overlay=0:0:shortest=1[v];"
             f"[0:a]volume={gain:.2f}dB,alimiter=limit=0.93,afade=in:st=0:d=0.03,"
             f"afade=out:st={dur - 0.18:.3f}:d=0.18[a]",
             "-map", "[v]", "-map", "[a]", "-frames:v", fr, "-t", f"{dur:.3f}", *self.venc, *self.aenc, out])
        print(f"segment {i + 1}: {key} {start:.2f}+{dur:.2f}s gain {gain:+.1f}dB")
        return out, key, start + dur

    def pipeline_card(self, key, a_start, gain_ref):
        pc = self.c["pipeline"]
        steps = [tuple(x) for x in pc["steps"]]
        pngs = pipeline_pngs(str(self.work / "pipe"), self.W, self.H, self.F, pc["heading"], steps, self.accent)
        step = pc.get("step_seconds", 0.8)
        hold = pc.get("hold_seconds", 2.0)
        lst = self.work / "pipe.txt"
        with open(lst, "w", encoding="utf-8") as f:
            for k, p in enumerate(pngs):
                f.write(f"file '{Path(p).as_posix()}'\nduration {hold if k == len(pngs) - 1 else step}\n")
            f.write(f"file '{Path(pngs[-1]).as_posix()}'\n")
        d = step * (len(pngs) - 1) + hold
        fr = self.frames(d)
        bg = pc.get("bg", {"src": key, "t": a_start})
        out = self.work / "pipeline.mp4"
        if cached(out):
            return out
        gain = self.target_db - mean_volume(self.src[key], a_start, d)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", bg["t"], "-i", self.src[bg["src"]],
             "-f", "concat", "-safe", 0, "-i", lst, "-ss", a_start, "-i", self.src[key], "-filter_complex",
             f"[0:v]{self.vnorm()},boxblur=30:3,eq=brightness=-0.36:saturation=0.55[b];"
             f"[1:v]fps={self.fps},format=rgba[o];[b][o]overlay=0:0:shortest=1,fade=in:0:4:color=white[v];"
             f"[2:a]volume={gain:.2f}dB,alimiter=limit=0.93,afade=out:st={d - 1.6:.3f}:d=1.6[a]",
             "-map", "[v]", "-map", "[a]", "-frames:v", fr, "-t", f"{fr / self.fps:.3f}", *self.venc, *self.aenc, out])
        return out

    def end_card(self):
        ec = self.c["end"]
        png = self.work / "end.png"
        end_png(png, self.W, self.H, self.F, ec["heading"], ec.get("items", []), ec.get("foot", ""), self.accent)
        d = ec.get("seconds", 4.0)
        out = self.work / "end.mp4"
        if cached(out):
            return out
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x07080f:s={self.W}x{self.H}:r={self.fps}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-loop", 1, "-i", png, "-filter_complex",
             f"[2:v]format=rgba,fade=in:st=0.2:d=0.6:alpha=1[o];[0:v][o]overlay=0:0:shortest=1,"
             f"fade=out:st={d - 0.8:.2f}:d=0.8,format=yuv420p[v]",
             "-map", "[v]", "-map", "1:a", "-frames:v", self.frames(d), "-t", d, *self.venc, *self.aenc, out])
        return out

    # -- assemble --------------------------------------------------------------------------
    def build(self):
        c = self.c
        pieces = []
        if c.get("montage"):
            parts, a0, mlen, per = self.montage()
            vids = parts[:]
            tlen = 0.0
            if c.get("title"):
                tv, tlen = self.title_card(c["title"].get("beats", 8), per)
                vids.append(tv)
            lst = self.work / "open.txt"
            lst.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in vids), encoding="utf-8")
            total = mlen + tlen
            fr = self.frames(total)
            gain = self.target_db - mean_volume(self.src[c["montage"]["audio"]["src"]], a0, total)
            out = self.work / "open.mp4"
            if not cached(out):
                run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", lst, "-ss", a0,
                     "-i", self.src[c["montage"]["audio"]["src"]], "-filter_complex",
                     f"[1:a]volume={gain:.2f}dB,alimiter=limit=0.93,afade=in:st=0:d=0.02,"
                     f"afade=out:st={total - 0.35:.3f}:d=0.35[a]",
                     "-map", "0:v", "-map", "[a]", "-frames:v", fr, "-t", f"{fr / self.fps:.3f}",
                     "-c:v", "copy", *self.aenc, out])
            pieces.append(out)
        segs = c["segments"]
        last = None
        for i, s in enumerate(segs):
            out, key, end_t = self.segment(i, s, len(segs))
            pieces.append(out)
            last = (key, end_t)
        if c.get("pipeline"):
            pieces.append(self.pipeline_card(last[0], last[1], None))
        if c.get("end"):
            pieces.append(self.end_card())
        lst = self.work / "all.txt"
        lst.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in pieces), encoding="utf-8")
        out = Path(c["out"])
        if not out.is_absolute():
            out = self.root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", 0, "-i", lst,
             "-c:v", "copy", *self.aenc, "-af", "aresample=async=1", "-movflags", "+faststart", out])
        print(f"-> {out}  ({ffprobe_dur(str(out)):.1f}s)")
        if c.get("share_720p", True):
            s720 = out.with_name(out.stem + "_720p.mp4")
            run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", out, "-vf", "scale=1280:720", "-c:v", "libx264",
                 "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                 "-movflags", "+faststart", s720])
            print(f"-> {s720}")


def main():
    sys.argv = [a for a in sys.argv if a != "--force"]
    if len(sys.argv) < 3 or sys.argv[1] not in ("analyze", "build"):
        print(__doc__)
        sys.exit(1)
    r = Reel(sys.argv[2])
    getattr(r, sys.argv[1])()


if __name__ == "__main__":
    main()
