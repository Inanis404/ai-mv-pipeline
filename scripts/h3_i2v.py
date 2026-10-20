"""Submit a MiniMax H3 image-to-video job to a local ComfyUI and wait for the mp4.

Modes: first frame only (fl2va), first+last frame, extra keyframes with --mid path@0.5, or
reference-to-video + Fun ControlNet with --control ctrl.mp4 (pose / depth / line video).
Needs the MiniMax H3 ComfyUI nodes + models (unet fl2va/ref2va int8, qwen3vl text encoder, video VAE,
fun controlnet, ref2v turbo LoRA) — names below must match your ComfyUI/models folders.
Env: COMFY_URL (default http://127.0.0.1:8188), COMFY_ROOT (ComfyUI folder with input/ output/).

usage: h3.py --first a.png [--last b.png] --prompt "..." --frames 39 --out clips/S011.mp4
             [--w 1280 --h 704] [--seed N] [--control ctrl.mp4 --cstrength 0.6] [--steps 20]
"""
import argparse, json, os, shutil, time, urllib.request, uuid

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
# ComfyUI install folder (the one that holds input/ and output/). Set COMFY_ROOT, e.g.
#   set COMFY_ROOT=D:\ComfyUI_windows_portable\ComfyUI
ROOT = os.environ.get("COMFY_ROOT") or os.path.expanduser("~/ComfyUI")
NEG = ("Keep the exact character design, colours and line art of the supplied frame(s). Premium modern anime, clean cel shading, crisp lineart, consistent face, "
       "smooth fluid anime motion, no flicker, no text, no subtitles, no watermark, no logo, no extra characters, no morphing faces, silent.")


def post(path, data):
    req = urllib.request.Request(COMFY + path, json.dumps(data).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def get(path):
    return json.loads(urllib.request.urlopen(COMFY + path).read())


def stage(src):
    """Copy an input file into ComfyUI/input with a unique name."""
    name = f"pp_{uuid.uuid4().hex[:8]}_{os.path.basename(src)}"
    shutil.copy(src, os.path.join(ROOT, "input", name))
    return name


def snap_len(n):
    k = max(0, -(-(n - 5) // 17))
    return 17 * k + 5


def build(a):
    wf = {
        "1": {"class_type": "LoadImage", "inputs": {"image": stage(a.first)}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "first_frame": ["1", 0],
            "prompt": a.prompt + " " + NEG, "width": a.w, "height": a.h, "length": snap_len(a.frames)}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": a.seed}},
        "7": {"class_type": "BasicGuider", "inputs": {"model": ["2", 0], "conditioning": ["5", 0]}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["2", 0], "scheduler": "simple", "steps": a.steps, "denoise": 1.0}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["6", 0], "guider": ["7", 0], "sampler": ["8", 0], "sigmas": ["9", 0], "latent_image": ["5", 1]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 24}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": "aimv/" + a.tag, "format": "auto", "codec": "auto"}},
    }
    cond = ["5", 0]
    for k, spec in enumerate(a.mid or []):
        path, frac = spec.rsplit("@", 1)
        L = snap_len(a.frames)
        idx = max(1, min(L - 2, int(round(float(frac) * (L - 1)))))
        wf[f"3{k}0"] = {"class_type": "LoadImage", "inputs": {"image": stage(path)}}
        wf[f"3{k}1"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
            "positive": cond, "vae": ["4", 0], "latent": ["5", 1], "image": [f"3{k}0", 0], "frame_idx": idx}}
        cond = [f"3{k}1", 0]
    wf["7"]["inputs"]["conditioning"] = cond
    if a.last:
        wf["14"] = {"class_type": "LoadImage", "inputs": {"image": stage(a.last)}}
        wf["5"]["inputs"]["last_frame"] = ["14", 0]
    if a.control:
        # the Fun ControlNet belongs with the ref2va model: reference-to-video conditioning,
        # first / intermediate / last keyframes anchored with AddGuide instead of fl2va's first/last inputs
        wf["2"]["inputs"]["unet_name"] = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        wf["5"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["3", 0], "vae": ["4", 0], "prompt": "<Picture 1> shows the exact look of the shot. " + a.prompt + " " + NEG,
            "width": a.w, "height": a.h, "length": snap_len(a.frames), "ref_image_size": "match",
            "ref_images.ref_image_1": ["1", 0]}}
        wf.pop("14", None)
        L = snap_len(a.frames)
        anchors = [(["1", 0], 0)]
        for k, spec in enumerate(a.mid or []):
            path, frac = spec.rsplit("@", 1)
            anchors.append(([f"3{k}0", 0], max(1, min(L - 2, int(round(float(frac) * (L - 1)))))))
        if a.last:
            wf["14"] = {"class_type": "LoadImage", "inputs": {"image": stage(a.last)}}
            anchors.append((["14", 0], -1))
        cond = ["5", 0]
        for k, (img, idx) in enumerate(anchors):
            wf[f"4{k}1"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
                "positive": cond, "vae": ["4", 0], "latent": ["5", 1], "image": img, "frame_idx": idx}}
            cond = [f"4{k}1", 0]
        for key in [k for k in wf if k.startswith("3") and k.endswith("1") and len(k) == 3]:
            wf.pop(key)  # drop the fl2va-path guide chain; images (3k0) are reused above
        wf["7"]["inputs"]["conditioning"] = cond
        wf["20"] = {"class_type": "LoadVideo", "inputs": {"file": stage(a.control)}}
        wf["21"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["20", 0]}}
        wf["22"] = {"class_type": "ImageScale", "inputs": {"image": ["21", 0], "upscale_method": "bilinear", "width": a.w, "height": a.h, "crop": "center"}}
        wf["23"] = {"class_type": "ModelPatchLoader", "inputs": {"name": "minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors"}}
        # turbo 4-step LoRA from the official Fun ControlNet template
        wf["25"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["2", 0], "lora_name": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", "strength_model": 1.0}}
        wf["9"]["inputs"]["model"] = ["25", 0]
        wf["9"]["inputs"]["steps"] = a.turbo_steps
        wf["24"] = {"class_type": "MiniMaxH3FunControlNetApply", "inputs": {
            "model": ["25", 0], "model_patch": ["23", 0], "vae": ["4", 0], "strength": a.cstrength,
            "start_percent": 0.0, "end_percent": a.cend, "control_video": ["22", 0]}}
        wf["7"]["inputs"]["model"] = ["24", 0]
    return wf


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--first", required=True)
    p.add_argument("--last")
    p.add_argument("--mid", action="append", help="intermediate keyframe as path@fraction (0-1), repeatable")
    p.add_argument("--prompt", required=True)
    p.add_argument("--frames", type=int, default=39)
    p.add_argument("--out", required=True)
    p.add_argument("--w", type=int, default=1344)
    p.add_argument("--h", type=int, default=768)
    p.add_argument("--seed", type=int, default=20261013)
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--control")
    p.add_argument("--cstrength", type=float, default=0.6)
    p.add_argument("--cend", type=float, default=0.6)
    p.add_argument("--turbo_steps", type=int, default=4)
    a = p.parse_args()
    a.tag = os.path.splitext(os.path.basename(a.out))[0] + "_" + uuid.uuid4().hex[:4]
    pid = post("/prompt", {"prompt": build(a)})["prompt_id"]
    t0 = time.time()
    while True:
        h = get("/history/" + pid)
        if pid in h:
            st = h[pid]["status"]
            if st.get("status_str") == "error":
                raise SystemExit("H3 error: " + json.dumps(st)[:2000])
            for nid, node in h[pid]["outputs"].items():
                if nid != "13":
                    continue
                for v in node.get("images", []) + node.get("videos", []) + node.get("gifs", []):
                    src = os.path.join(ROOT, "output", v.get("subfolder", ""), v["filename"])
                    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
                    shutil.copy(src, a.out)
                    print(f"done {a.out} in {time.time()-t0:.0f}s")
                    return
            raise SystemExit("no output: " + json.dumps(h[pid])[:1000])
        time.sleep(3)


if __name__ == "__main__":
    main()
