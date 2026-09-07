#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
播客音频 → 转录文本 + 带时间戳分段。

流程：下载 m4a → ffmpeg 转 16k 单声道 wav → mlx-whisper 转录 → 落盘。
播客没有画面，所以**不抽帧**；本 skill 的产物比视频类 skill 少一个 frames/ 目录。

用法:
    python3 media.py --meta /tmp/xyz_work/meta.json --workdir /tmp/xyz_work
    python3 media.py --meta meta.json --workdir w --model mlx-community/whisper-large-v3
    python3 media.py --meta meta.json --workdir w --offline      # 强制离线（模型已缓存时最稳）

产物（workdir 下）:
    audio.m4a        原始音频
    audio.wav        16k/mono，转录输入
    transcript.txt   纯文本转录（Whisper 中文输出通常无标点，属正常现象）
    segments.json    [{start, end, text}] 带时间戳分段 —— 时间轴导航的唯一数据源
    meta.json        回填实际时长与字数

环境坑（已在脚本内自愈，勿删）:
    1. 代理环境下 huggingface.co 常 502 → 自动切 hf-mirror.com
    2. HuggingFace Xet 后端会 401 → 自动 HF_HUB_DISABLE_XET=1
    3. 模型已缓存时强制联网反而失败 → 检测到缓存自动 HF_HUB_OFFLINE=1
    4. mlx-whisper 硬编码调用 `ffmpeg` 命令名 → 用 imageio 的 ffmpeg 建同名软链并加 PATH
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

# ---- 环境自愈：必须在 import mlx_whisper 之前设置 ----
if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"):
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def has_cached_model(repo: str) -> bool:
    """判断 HF 缓存里是否已有该模型（有则离线跑最稳）。"""
    root = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    slug = "models--" + repo.replace("/", "--")
    d = os.path.join(root, "hub", slug)
    return os.path.isdir(d)


def ensure_ffmpeg_link() -> str:
    """mlx-whisper 内部直接调 `ffmpeg`，把 imageio 的二进制挂成同名命令。"""
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    link_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(link_dir, exist_ok=True)
    link = os.path.join(link_dir, "ffmpeg")
    if not os.path.exists(link):
        try:
            os.symlink(exe, link)
        except OSError:
            pass  # 已存在或无权建链时，靠 PATH 里的系统 ffmpeg
    os.environ["PATH"] = link_dir + os.pathsep + os.environ.get("PATH", "")
    return exe


def download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        t0 = time.time()
        while True:
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if total:
                pct = done * 100 // total
                print(f"\r  下载 {done/1e6:.1f}/{total/1e6:.1f} MB ({pct}%)", end="", flush=True)
    print(f"\r  下载完成 {done/1e6:.1f} MB，用时 {time.time()-t0:.0f}s", flush=True)


def probe_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        try:
            return float(r.stdout.strip())
        except ValueError:
            pass
    # 没有 ffprobe 时回退 ffmpeg（stderr 里有 Duration 行）
    r = subprocess.run(["ffmpeg", "-i", path], capture_output=True, text=True)
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True, help="fetch_episode.py 产出的 meta.json")
    ap.add_argument("--workdir", default="/tmp/xyz_work")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="zh")
    ap.add_argument("--offline", action="store_true", help="强制离线（模型已缓存）")
    ap.add_argument("--skip-download", action="store_true", help="音频已在本地时跳过下载")
    args = ap.parse_args()

    with open(args.meta, encoding="utf-8") as f:
        meta = json.load(f)
    audio_url = meta.get("audio_url") or ""
    if not audio_url:
        sys.exit("meta.json 里没有 audio_url —— 付费/私密单集，走降级告知。")

    wd = args.workdir
    os.makedirs(wd, exist_ok=True)
    m4a = os.path.join(wd, "audio.m4a")
    wav = os.path.join(wd, "audio.wav")

    if args.offline or has_cached_model(args.model):
        os.environ["HF_HUB_OFFLINE"] = "1"
        print("[env] 检测到本地模型缓存 → 离线模式", flush=True)

    # 1) 下载
    if args.skip_download and os.path.exists(m4a):
        print("[1/3] 已有本地音频，跳过下载", flush=True)
    else:
        print("[1/3] 下载音频", flush=True)
        download(audio_url, m4a)

    ffmpeg = ensure_ffmpeg_link()

    # 2) 转 wav（16k 单声道是 Whisper 的期望输入）
    if not os.path.exists(wav):
        print("[2/3] 转码 16k/mono wav", flush=True)
        r = subprocess.run(
            [ffmpeg, "-y", "-i", m4a, "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", wav],
            capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"转码失败：{r.stderr[-600:]}")
    dur = probe_duration(m4a) or float(meta.get("duration_sec") or 0)
    print(f"  时长 {dur/60:.1f} 分钟", flush=True)

    # 3) 转录
    print(f"[3/3] 转录（{args.model}），长播客请耐心——约 10-13 倍实时", flush=True)
    import mlx_whisper
    t0 = time.time()
    res = mlx_whisper.transcribe(wav, path_or_hf_repo=args.model,
                                 language=args.language)
    elapsed = time.time() - t0

    text = res.get("text", "") if isinstance(res, dict) else str(res)
    segs = res.get("segments", []) if isinstance(res, dict) else []

    with open(os.path.join(wd, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(wd, "segments.json"), "w", encoding="utf-8") as f:
        json.dump([{"start": round(s.get("start", 0.0), 2),
                    "end": round(s.get("end", 0.0), 2),
                    "text": s.get("text", "")} for s in segs],
                  f, ensure_ascii=False, indent=2)

    meta["duration_sec"] = dur
    meta["chars"] = len(text)
    meta["segments"] = len(segs)
    meta["transcribe_sec"] = round(elapsed, 1)
    with open(args.meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    speed = (dur / elapsed) if elapsed else 0
    print(f"\n转录完成：{len(text)} 字 / {len(segs)} 段 | 耗时 {elapsed/60:.1f} 分钟"
          f"（约 {speed:.0f}× 实时）", flush=True)
    print(f"产物: {wd}/transcript.txt  {wd}/segments.json", flush=True)
    if len(text) < 200:
        print("\n⚠️  转录文本过短 —— 可能是纯音乐/空音频，请走降级告知。")


if __name__ == "__main__":
    main()
