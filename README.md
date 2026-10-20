# ai-mv-pipeline-skill

AI 管线自动出 MV 的 skill：一首歌 → 节拍/段落分析 → 歌词对齐 → 分镜 (`shots.py`) → 角色一致关键帧
→ MiniMax H3 图生视频 (ComfyUI) → 超分 → 代码合成 (歌词排版 + 后期) → 审片 → 交付。
外加一个把成片混剪成宣传片的脚本。

## Layout

```
SKILL.md                    skill entry point (frontmatter + phases + rules)
references/pipeline.md      each phase: outputs, checks, prompt blocks, failure fixes
references/showreel.md      showreel workflow + config reference + lessons
scripts/promo_reel.py       analyze / build a beat-synced showreel from finished MVs
scripts/h3_i2v.py           one MiniMax H3 image-to-video job via local ComfyUI (first/last/mid frames, ControlNet)
scripts/prep_clip.py        H3 clip -> Real-ESRGAN x2 -> 1080p JPEG sequence
templates/shots.py          shot list template (beat-snapped, flags)
templates/kf.py             keyframe jobs with character refs
templates/h3_jobs.py        batch H3 for every non-still shot, reruns for QA failures
examples/promo_config.json  showreel config template
```

## Install as a Claude skill

Copy the folder to `~/.claude/skills/ai-mv-pipeline/` or upload it as a skill in Claude.

Requirements: Python 3.9+ (numpy, Pillow), ffmpeg/ffprobe on PATH. For generation: ComfyUI + MiniMax H3
models, Real-ESRGAN ncnn-vulkan, an image model (Codex image gen or NovelAI). For a code compositor:
Node + Playwright.

## Showreel quick start

```bash
python scripts/promo_reel.py analyze examples/promo_config.json
python scripts/promo_reel.py build   examples/promo_config.json
```
