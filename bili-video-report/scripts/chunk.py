#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把长视频的 transcript / segments.json 切成可逐块摘要的小块。

为什么需要：3 小时课程约 5.6 万字（60–70k tokens），全量塞进上下文会爆，
而且单次成稿质量反而下降——模型在超长输入里会漏掉中段内容。
正确做法是：分块 → 逐块摘要 → 合并成稿。

分档策略（与 SKILL.md 一致）：
    < 30 分钟   不切块，全量转录直接成稿
    30–90 分钟  按 15 分钟一块切
    > 90 分钟   建议改按「分 P」独立处理（--pages N），切块只作兜底

用法:
    python3 chunk.py --workdir /tmp/bili_work                 # 按时长自动分档
    python3 chunk.py --workdir /tmp/bili_work --block 600     # 强制 10 分钟一块
    python3 chunk.py --workdir /tmp/bili_work --max-chars 6000

产物（在 workdir/chunks/ 下）:
    chunk_01.md  每块带时间范围标题（[MM:SS - MM:SS]）与正文
    manifest.json  块清单：序号 / 起止时间 / 字数 / 文件名
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def mmss(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def policy(duration: float) -> tuple[int, str]:
    """按时长返回 (每块秒数, 策略说明)。"""
    if duration < 30 * 60:
        return 0, "时长 <30 分钟：不切块，全量转录直接成稿"
    if duration <= 90 * 60:
        return 15 * 60, "时长 30–90 分钟：按 15 分钟分块，逐块摘要后合并成稿"
    return 15 * 60, ("时长 >90 分钟：优先按「分 P」独立处理"
                     "（fetch_bili.py --pages N）；此处仍按 15 分钟切块兜底")


def split_by_time(segs: list, block: int) -> list[list]:
    """按时间边界切块，保证每块内容时间连续。"""
    chunks: list[list] = []
    cur: list = []
    cur_start = segs[0]["start"] if segs else 0.0
    for s in segs:
        if cur and s["start"] - cur_start >= block:
            chunks.append(cur)
            cur = []
            cur_start = s["start"]
        cur.append(s)
    if cur:
        chunks.append(cur)
    return chunks


def split_by_chars(segs: list, max_chars: int) -> list[list]:
    """按字数切块，避免某块文字过长。"""
    chunks: list[list] = []
    cur: list = []
    n = 0
    for s in segs:
        cur.append(s)
        n += len(s.get("text", ""))
        if n >= max_chars:
            chunks.append(cur)
            cur, n = [], 0
    if cur:
        chunks.append(cur)
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/tmp/bili_work")
    ap.add_argument("--block", type=int, default=0,
                    help="每块秒数，默认按时长自动分档")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="每块最大字数，与时间切块取更严格者")
    args = ap.parse_args()

    wd = args.workdir
    seg_path = os.path.join(wd, "segments.json")
    meta_path = os.path.join(wd, "meta.json")
    if not os.path.exists(seg_path):
        sys.exit(f"找不到 {seg_path}。先跑 media.py 生成带时间戳的分段。")

    with open(seg_path, encoding="utf-8") as f:
        segs = json.load(f)
    if not segs:
        sys.exit("segments.json 为空——大概率是无口播视频，走降级告知即可。")

    duration = 0.0
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            duration = float(json.load(f).get("duration_sec") or 0.0)
    if not duration:
        duration = segs[-1].get("end", 0.0)

    block, note = policy(duration)
    if args.block:
        block = args.block
        note = f"手动指定：每块 {args.block} 秒"

    outdir = os.path.join(wd, "chunks")
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):
        if old.startswith("chunk_"):
            os.remove(os.path.join(outdir, old))

    if block <= 0:
        parts = [segs]
        note += "（实际不切块）"
    else:
        parts = split_by_time(segs, block)
        if args.max_chars:
            parts = [c for p in parts for c in split_by_chars(p, args.max_chars)]

    manifest = []
    for i, part in enumerate(parts, 1):
        start, end = part[0]["start"], part[-1].get("end", part[-1]["start"])
        text = "".join(s.get("text", "") for s in part)
        name = f"chunk_{i:02d}.md"
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
            f.write(f"# 第 {i} 块 · {mmss(start)} – {mmss(end)}\n\n{text}\n")
        manifest.append({"index": i, "start": round(start, 1),
                         "end": round(end, 1), "chars": len(text),
                         "file": f"chunks/{name}"})

    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"duration_sec": round(duration, 1), "policy": note,
                   "chunks": manifest}, f, ensure_ascii=False, indent=2)

    print(f"[分块] 总时长 {mmss(duration)} → {len(parts)} 块 | {note}")
    for m in manifest:
        print(f"   {m['index']:02d}  {mmss(m['start'])}–{mmss(m['end'])}"
              f"  {m['chars']:>6} 字  {m['file']}")
    print(f"[产物] {outdir}/manifest.json")


if __name__ == "__main__":
    main()
