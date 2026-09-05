#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境自检：确认 xhs-video-report 的全部依赖是否就位。

用法:
    python3 selfcheck.py

全绿才能跑通完整流程。任一项红了按提示修。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

OBSIDIAN = os.path.expanduser("~/Obsidian")
MODEL = os.environ.get("XHS_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

ok_all = True


def check(name: str, fn):
    global ok_all
    try:
        status, detail = fn()
    except Exception as e:  # noqa: BLE001
        status, detail = False, f"{type(e).__name__}: {e}"
    mark = "OK  " if status else "FAIL"
    if not status:
        ok_all = False
    print(f"[{mark}] {name:<22} {detail}")
    return status


def _bsk_path():
    p = os.path.expanduser("~/.local/bin/bsk")
    if os.path.exists(p):
        return p
    return shutil.which("bsk")


def c_bsk():
    p = _bsk_path()
    if not p:
        return False, "未找到，装 browser-skill 后应在 ~/.local/bin/bsk"
    return True, p


def c_bsk_doctor():
    p = _bsk_path()
    if not p:
        return False, "跳过（无 bsk）"
    r = subprocess.run([p, "doctor"], capture_output=True, text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    if "extension connected" in out and "FAIL" not in out.split("extension connected")[0]:
        pass
    fails = [ln for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    if fails:
        # minor drift 是协议小版本差异，实测不影响命令执行 → 放行为通过
        drift = [f for f in fails if "minor drift" in f]
        if len(fails) == len(drift):
            return True, "在线（存在协议 minor drift，通常不影响）"
        return False, " ; ".join(f.strip() for f in fails[:2])
    return True, "daemon + 扩展均在线"


def c_ffmpeg():
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([p, "-version"], capture_output=True, text=True, timeout=30)
        ver = (r.stdout or "").splitlines()[0] if r.stdout else "?"
        return os.path.exists(p), ver
    except ImportError:
        w = shutil.which("ffmpeg")
        return (bool(w), w or "未安装，pip install imageio-ffmpeg")


def c_mlx():
    try:
        import mlx.core as mx
        import mlx_whisper  # noqa: F401
        return True, f"mlx 可用，设备 {mx.default_device()}"
    except ImportError as e:
        return False, f"未安装: {e}"


def c_model():
    cache = os.path.expanduser("~/.cache/huggingface/hub")
    if not os.path.isdir(cache):
        return False, "模型未缓存，首次转录会下载约 1.5GB"
    # 模型 id → cache 目录名: mlx-community/whisper-large-v3-turbo → models--mlx-community--whisper-large-v3-turbo
    want = "models--" + MODEL.replace("/", "--")
    if os.path.isdir(os.path.join(cache, want)):
        return True, f"已缓存: {MODEL}"
    hit = [d for d in os.listdir(cache) if d.startswith("models--") and "whisper" in d]
    if hit:
        return True, f"缓存了 {len(hit)} 个 whisper 模型，但目标 {MODEL} 不在其中（将现场下载）"
    return False, f"未缓存 {MODEL}，首次转录需下载约 1.5GB"


def c_obsidian():
    if os.path.isdir(OBSIDIAN):
        return True, OBSIDIAN
    return False, f"目录不存在: {OBSIDIAN}"


def main():
    print("xhs-video-report 环境自检\n" + "-" * 56)
    check("bsk CLI", c_bsk)
    check("浏览器扩展连接", c_bsk_doctor)
    check("ffmpeg", c_ffmpeg)
    check("mlx-whisper", c_mlx)
    check("whisper 模型缓存", c_model)
    check("Obsidian 目录", c_obsidian)
    print("-" * 56)
    if ok_all:
        print("全部就绪，可以跑完整流程。")
    else:
        print("有项未就绪，按上面提示修复后再跑。")
        sys.exit(1)


if __name__ == "__main__":
    main()
