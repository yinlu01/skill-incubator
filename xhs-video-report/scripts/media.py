#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载视频 → 抽音频 → 转录 → 抽关键帧。

用法:
    python3 media.py --meta /tmp/xhs_meta.json --workdir /tmp/xhs_work
    python3 media.py --video-url "<直链>" --workdir /tmp/xhs_work   # 跳过 meta

产物（都在 workdir 下）:
    video.mp4        原始视频
    audio.wav        16k 单声道音频
    transcript.txt   口播全文
    frames/f_01.jpg  关键帧
    meta.json        时长、帧列表等
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    # 踩坑：imageio 的二进制名带平台后缀（ffmpeg-macos-aarch64-v7.1），
    # 而 mlx_whisper 内部硬编码 subprocess 调 `ffmpeg` 命令 → 必须建同名软链
    # 并把所在目录塞进 PATH，否则报 FileNotFoundError: 'ffmpeg'
    _dir = os.path.dirname(FFMPEG)
    _link = os.path.join(_dir, "ffmpeg")
    if not os.path.exists(_link):
        try:
            os.symlink(FFMPEG, _link)
        except OSError:
            pass  # 无写权限时静默，下面 PATH 仍会带上该目录
    os.environ["PATH"] = _dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

# 网络策略（踩坑固化）：
# 1) 代理环境下 huggingface.co 常返回 502 Bad Gateway → 切国内镜像
# 2) 镜像站下 Xet 存储后端会 401 Unauthorized → 禁用后回退传统 HTTP 下载
# 两者都用 setdefault，用户可用环境变量覆盖。
if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"):
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

WHISPER_MODEL = os.environ.get(
    "XHS_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TARGET_FRAMES = 10


def sh(cmd: list[str], **kw) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def probe_duration(path: str) -> float:
    code, out = sh([FFMPEG, "-i", path])
    # Duration: 00:03:45.12
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 0.0


def download(url: str, dest: str) -> bool:
    if url.startswith("file://") or os.path.exists(url):
        shutil.copy(url.replace("file://", ""), dest)
        return True
    code, out = sh([
        "curl", "-L", "--compressed", "-o", dest,
        "-H", f"User-Agent: {UA}",
        "-H", "Referer: https://www.xiaohongshu.com/",
        "--max-time", "600", url,
    ], timeout=620)
    ok = code == 0 and os.path.exists(dest) and os.path.getsize(dest) > 1024
    if not ok:
        print(f"[下载失败] code={code}\n{out[:600]}", file=sys.stderr)
    return ok


def extract_audio(video: str, wav: str) -> bool:
    code, out = sh([FFMPEG, "-y", "-i", video, "-vn",
                    "-ac", "1", "-ar", "16000", "-f", "wav", wav], timeout=600)
    if code != 0:
        print(f"[抽音频失败]\n{out[:600]}", file=sys.stderr)
    return code == 0


def transcribe(wav: str, txt: str) -> str:
    import mlx_whisper
    print(f"[转录] 模型 {WHISPER_MODEL}（首次会下载，约 1.5GB）", file=sys.stderr)
    res = mlx_whisper.transcribe(wav, path_or_hf_repo=WHISPER_MODEL)
    text = (res or {}).get("text", "") if isinstance(res, dict) else str(res)
    text = text.strip()
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def extract_frames(video: str, frames_dir: str, duration: float) -> list[str]:
    os.makedirs(frames_dir, exist_ok=True)
    if duration <= 0:
        duration = 300.0
    # 自适应间隔：目标 TARGET_FRAMES 张，单视频最多 20 张
    n = max(4, min(TARGET_FRAMES, 20))
    interval = max(3.0, duration / n)
    out_pattern = os.path.join(frames_dir, "f_%02d.jpg")
    code, out = sh([FFMPEG, "-y", "-i", video,
                    "-vf", f"fps=1/{interval:.1f},scale=960:-1",
                    "-q:v", "4", out_pattern], timeout=600)
    if code != 0:
        print(f"[抽帧失败]\n{out[:600]}", file=sys.stderr)
        return []
    return sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir)
                  if f.endswith(".jpg"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", help="fetch_meta.py 产出的 json")
    ap.add_argument("--video-url", help="直接给直链，跳过 meta")
    ap.add_argument("--workdir", default="/tmp/xhs_work")
    ap.add_argument("--no-transcribe", action="store_true")
    args = ap.parse_args()

    wd = args.workdir
    os.makedirs(wd, exist_ok=True)
    meta = {}
    if args.meta:
        with open(args.meta, encoding="utf-8") as f:
            meta = json.load(f)

    url = args.video_url or meta.get("video", "")
    if not url:
        sys.exit("没有视频直链。先跑 fetch_meta.py，或用 --video-url 指定。")

    video = os.path.join(wd, "video.mp4")
    print(f"[1/4] 下载 → {video}", file=sys.stderr)
    if not download(url, video):
        sys.exit(1)

    duration = probe_duration(video)
    print(f"[2/4] 抽音频（时长 {duration:.0f}s）", file=sys.stderr)
    wav = os.path.join(wd, "audio.wav")
    if not extract_audio(video, wav):
        sys.exit(1)

    transcript = ""
    if args.no_transcribe:
        print("[3/4] 跳过转录", file=sys.stderr)
    else:
        print("[3/4] 转录", file=sys.stderr)
        txt = os.path.join(wd, "transcript.txt")
        transcript = transcribe(wav, txt)
        print(f"      转录 {len(transcript)} 字", file=sys.stderr)

    print("[4/4] 抽关键帧", file=sys.stderr)
    frames = extract_frames(video, os.path.join(wd, "frames"), duration)

    out_meta = {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "desc": meta.get("desc", ""),
        "url": meta.get("url", ""),
        "video_url": url,
        "duration_sec": round(duration, 1),
        "transcript_chars": len(transcript),
        "frames": frames,
        "video_path": video,
    }
    with open(os.path.join(wd, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(out_meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(out_meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
