#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站视频抓取：解析链接 → 取元数据/分P → 探测字幕 → 下载视频。

设计依据（2026-09-05 真机实测，别凭直觉改）：
1. 公开 API（web-interface/view、player/v2）**免登录、免 wbi 签名**，直接返回 code 0
   → 元数据层不需要浏览器，也不需要第三方 skill 那套 wbi 签名算法。
2. yt-dlp 裸跑被 412 Precondition Failed 拦截
   → 必须注入浏览器 cookie。cookie 用 bsk 从已登录浏览器导出，缓存复用。
3. 5 条样本视频的 CC 字幕**全为空**（subtitles: []）
   → 字幕仅作可选加速，拿不到是常态，转录才是主路径。

用法:
    python3 fetch_bili.py "<B站链接或BV号>" [--out meta.json] [--workdir DIR]
                          [--pages 1] [--no-download] [--refresh-cookie]

输出 JSON:
    {
      "ok": true, "bvid": "BV...", "title": "...", "author": "...",
      "desc": "...", "duration_sec": 1190, "pages": [...],
      "page": 1, "cid": 123, "subtitle": "字幕全文或空",
      "video_path": "/tmp/bili_work/video.mp4", "diagnosis": "..."
    }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REFERER = "https://www.bilibili.com/"
API_VIEW = "https://api.bilibili.com/x/web-interface/view"
API_PLAYER = "https://api.bilibili.com/x/player/v2"
COOKIE_CACHE = os.path.expanduser("~/.cache/bili-video-report/cookies.txt")
BSK_CANDIDATES = [os.path.expanduser("~/.local/bin/bsk"),
                  "/usr/local/bin/bsk", "bsk"]


def find_bsk() -> str:
    for p in BSK_CANDIDATES:
        if os.path.exists(p):
            return p
        if p == "bsk" and shutil.which("bsk"):
            return shutil.which("bsk")
    return ""


def ffmpeg_dir() -> str:
    """imageio 的 ffmpeg 目录，加到 PATH 让 yt-dlp 能找到它。"""
    try:
        import imageio_ffmpeg
        return os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return ""


def http_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER,
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", f"命令不存在: {cmd[0]}"


# ---------------------------------------------------------------- 链接解析

def resolve_bvid(raw: str) -> str:
    """支持：BV号 / av号 / 完整URL / b23.tv短链 / 带分P参数。"""
    raw = raw.strip()
    m = re.search(r"(BV[0-9A-Za-z]{10})", raw)
    if m:
        return m.group(1)
    m = re.search(r"\bav(\d{1,15})\b", raw, re.I)
    if m:
        return "av" + m.group(1)

    # 短链 b23.tv 需跟随跳转
    if "b23.tv" in raw or "bili2233.cn" in raw:
        if not raw.startswith("http"):
            raw = "https://" + raw
        req = urllib.request.Request(raw, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                final = r.geturl()
            m = re.search(r"(BV[0-9A-Za-z]{10})", final)
            if m:
                return m.group(1)
            sys.exit(f"短链跳转后没找到 BV 号：{final}")
        except urllib.error.URLError as e:
            sys.exit(f"短链解析失败：{e}")

    if not raw.startswith("http"):
        sys.exit(f"无法从输入解析 BV/av 号：{raw}")
    try:
        html = http_text(raw)
        m = re.search(r"(BV[0-9A-Za-z]{10})", html)
        if m:
            return m.group(1)
    except Exception as e:
        sys.exit(f"打开链接失败：{e}")
    sys.exit(f"页面里没找到 BV 号：{raw}")


def parse_page_arg(spec: str, total: int) -> list[int]:
    """--pages 1 | 1-3 | 1,3,5 | all"""
    spec = (spec or "1").strip().lower()
    if spec in ("all", "*"):
        return list(range(1, total + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted({p for p in out if 1 <= p <= total})


# ---------------------------------------------------------------- cookie

def export_cookie_via_bsk(dest: str) -> tuple[int, str]:
    """用 bsk 从已登录浏览器导出 B 站 cookie，转 Netscape 格式给 yt-dlp。"""
    bsk = find_bsk()
    if not bsk:
        return 0, "找不到 bsk（browser-skill），无法导出 cookie"

    sid = ""
    code, out, err = run([bsk, "session", "start", "--json"], timeout=60)
    if code == 0:
        try:
            data = json.loads(out)
            for k in ("session", "sessionId", "session_id", "id"):
                if k in data:
                    sid = str(data[k])
                    break
        except Exception:
            m = re.search(r"\b([a-z0-9]{4})\b", out)
            if m:
                sid = m.group(1)
    if not sid:
        return 0, f"bsk session start 失败：{err or out}"

    try:
        run([bsk, "navigate", "https://www.bilibili.com/", "--session", sid],
            timeout=90)
        time.sleep(4)
        code, out, err = run(
            [bsk, "evaluate", "document.cookie", "--session", sid, "--json"],
            timeout=60)
    finally:
        run([bsk, "session", "stop", sid], timeout=30)

    if code != 0:
        return 0, f"读取 cookie 失败：{err or out}"

    raw = out
    try:
        probe = json.loads(out)
        if isinstance(probe, dict):
            # bsk --json 把返回值包在 "value" 键里（v0.1.10 实测）
            for k in ("value", "result", "data"):
                if isinstance(probe.get(k), str):
                    raw = probe[k]
                    break
    except Exception:
        pass

    pairs = []
    for seg in raw.split(";"):
        seg = seg.strip()
        if "=" in seg:
            k, v = seg.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                pairs.append((k, v))
    if not pairs:
        return 0, f"document.cookie 为空（浏览器未登录 B 站？）原始输出：{raw[:200]}"

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    expiry = int(time.time()) + 3600 * 24 * 365
    with open(dest, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for k, v in pairs:
            f.write(f".bilibili.com\tTRUE\t/\tFALSE\t{expiry}\t{k}\t{v}\n")
    return len(pairs), dest


def ensure_cookie(refresh: bool = False) -> tuple[str, str]:
    if refresh and os.path.exists(COOKIE_CACHE):
        os.remove(COOKIE_CACHE)
    if os.path.exists(COOKIE_CACHE):
        return COOKIE_CACHE, "复用缓存 cookie"
    n, msg = export_cookie_via_bsk(COOKIE_CACHE)
    if n:
        return COOKIE_CACHE, f"新导出 {n} 条 cookie"
    return "", msg


# ---------------------------------------------------------------- 字幕

def try_subtitle(bvid: str, cid: int) -> str:
    """探测 CC 字幕。实测多数视频为空，拿不到是常态，返回空串即可。"""
    try:
        data = http_json(f"{API_PLAYER}?bvid={bvid}&cid={cid}")
    except Exception as e:
        return f"[字幕接口失败] {e}" and ""
    sub = ((data.get("data") or {}).get("subtitle") or {})
    items = sub.get("subtitles") or []
    if not items:
        return ""
    # 优先中文
    zh = [s for s in items if str(s.get("lan", "")).startswith("zh")]
    pick = (zh or items)[0]
    url = pick.get("subtitle_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        return ""
    try:
        raw = json.loads(http_text(url))
        return "\n".join(b.get("content", "") for b in raw.get("body") or [])
    except Exception:
        return ""


# ---------------------------------------------------------------- 下载

def http_json_cookie(url: str, cookie_path: str, timeout: int = 20) -> dict:
    """带 cookie 的 JSON 请求。http.cookiejar 能直接读 Netscape 格式。"""
    import http.cookiejar
    cj = http.cookiejar.MozillaCookieJar()
    if cookie_path and os.path.exists(cookie_path):
        try:
            cj.load(cookie_path, ignore_discard=True, ignore_expires=True)
        except Exception:
            pass
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": REFERER,
        "Accept": "application/json, text/plain, */*"})
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def pick_stream(dash: dict, max_height: int = 720) -> tuple[str, str]:
    """从 DASH 清单里挑一路视频 + 一路音频。取 ≤max_height 的最高画质。"""
    vids = dash.get("video") or []
    auds = dash.get("audio") or []
    if not vids:
        return "", ""
    ok = [v for v in vids if (v.get("height") or 0) <= max_height] or vids
    v = max(ok, key=lambda x: (x.get("height") or 0, x.get("bandwidth") or 0))
    a = max(auds, key=lambda x: x.get("bandwidth") or 0) if auds else None
    return v.get("baseUrl") or v.get("base_url") or "", (
        a.get("baseUrl") or a.get("base_url") or "") if a else ""


def dash_download(vurl: str, aurl: str, dest: str) -> tuple[bool, str]:
    """ffmpeg 直下 DASH 分片并合并。B 站要求带 Referer，否则 403。"""
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    hdr = (f"Referer: {REFERER}\r\nUser-Agent: {UA}\r\n")
    cmd = [ffmpeg, "-y", "-headers", hdr]
    if vurl:
        cmd += ["-headers", hdr, "-i", vurl]
    if aurl:
        cmd += ["-headers", hdr, "-i", aurl]
    if vurl and aurl:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-c", "copy", "-bsf:a", "aac_adtstoasc", dest]
    code, out, err = run(cmd, timeout=1200)
    if code == 0 and os.path.exists(dest):
        return True, f"下载成功（{os.path.getsize(dest)//1024//1024}MB）"
    return False, (err or out)[-600:]


def download(bvid: str, cid: int, dest: str, cookie: str) -> tuple[bool, str]:
    """取播放地址 → ffmpeg 下载。

    为什么不用 yt-dlp（实测踩坑）：yt-dlp 走 x/player/wbi/v2，本机会稳定
    返回 412 Precondition Failed；而老接口 x/player/playurl 带 cookie 直接
    返回 code 0，连 wbi 签名都不需要。少一个依赖、少一层风控，何乐不为。
    """
    try:
        data = http_json_cookie(
            f"https://api.bilibili.com/x/player/playurl?bvid={bvid}"
            f"&cid={cid}&fnval=16&qn=64&fourk=0", cookie)
    except Exception as e:
        return False, f"playurl 接口失败：{e}"
    if data.get("code") != 0:
        return False, f"playurl 返回 {data.get('code')}: {data.get('message')}"

    d = data.get("data") or {}
    vurl, aurl = pick_stream(d.get("dash") or {})
    if not vurl:
        # 老视频走 durl（整段 mp4/flv，无分片）
        durls = d.get("durl") or []
        if durls:
            return dash_download("", durls[0].get("url", ""), dest)
        return False, ("没有可用流。大会员/付费视频需要 SESSDATA"
                       "（HttpOnly，JS 读不到）→ 请降级为「仅元数据」报告。")

    ok, msg = dash_download(vurl, aurl, dest)
    if not ok and "403" in msg:
        # cookie 可能被风控刷新，重导一次
        os.remove(cookie)
        new_cookie, _ = ensure_cookie(refresh=True)
        if new_cookie:
            data = http_json_cookie(
                f"https://api.bilibili.com/x/player/playurl?bvid={bvid}"
                f"&cid={cid}&fnval=16&qn=64&fourk=0", new_cookie)
            v2, a2 = pick_stream((data.get("data") or {}).get("dash") or {})
            if v2:
                ok, msg = dash_download(v2, a2, dest)
    return ok, msg


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="B 站链接 / BV号 / av号 / b23.tv 短链")
    ap.add_argument("--out", default="/tmp/bili_meta.json")
    ap.add_argument("--workdir", default="/tmp/bili_work")
    ap.add_argument("--pages", default="1", help="分P：1 / 1-3 / 1,3 / all")
    ap.add_argument("--no-download", action="store_true", help="只取元数据")
    ap.add_argument("--refresh-cookie", action="store_true")
    args = ap.parse_args()

    bvid = resolve_bvid(args.url)
    print(f"[解析] {bvid}", file=sys.stderr)

    result = {"ok": False, "bvid": bvid, "title": "", "author": "", "desc": "",
              "duration_sec": 0, "pic": "", "pages": [], "page": 1, "cid": 0,
              "subtitle": "", "video_path": "", "diagnosis": ""}

    try:
        data = http_json(f"{API_VIEW}?bvid={bvid}")
    except Exception as e:
        result["diagnosis"] = f"元数据接口失败：{e}"
        _dump(result, args.out)
        sys.exit(1)
    if data.get("code") != 0:
        result["diagnosis"] = f"元数据接口返回 {data.get('code')}: {data.get('message')}"
        _dump(result, args.out)
        sys.exit(1)

    d = data["data"]
    pages = d.get("pages") or []
    result.update({
        "title": d.get("title", ""),
        "author": (d.get("owner") or {}).get("name", ""),
        "desc": (d.get("desc") or "")[:3000],
        "duration_sec": d.get("duration", 0),
        "pic": d.get("pic", ""),
        "pages": [{"page": p.get("page"), "cid": p.get("cid"),
                   "part": p.get("part", ""), "duration": p.get("duration", 0)}
                  for p in pages],
        "url": f"https://www.bilibili.com/video/{bvid}",
    })
    total = len(pages) or 1
    chosen = parse_page_arg(args.pages, total)
    if not chosen:
        result["diagnosis"] = f"--pages={args.pages} 超出范围（共 {total} P）"
        _dump(result, args.out)
        sys.exit(1)

    print(f"[元数据] 《{result['title']}》 UP:{result['author']} 共 {total} P",
          file=sys.stderr)

    os.makedirs(args.workdir, exist_ok=True)
    if args.no_download:
        result["ok"] = True
        result["diagnosis"] = "仅元数据模式"
        _dump(result, args.out)
        return

    # 只处理第一 P（多 P 全流程在 SKILL.md 里说明：逐 P 调用）
    page = chosen[0]
    result["page"] = page
    result["cid"] = pages[page - 1]["cid"] if pages else d.get("cid", 0)

    result["subtitle"] = try_subtitle(bvid, result["cid"])
    if result["subtitle"]:
        print(f"[字幕] 命中 CC 字幕 {len(result['subtitle'])} 字", file=sys.stderr)
    else:
        print("[字幕] 无（常态，走转录）", file=sys.stderr)

    cookie, cmsg = ensure_cookie(args.refresh_cookie)
    if not cookie:
        result["diagnosis"] = f"cookie 不可用：{cmsg}"
        _dump(result, args.out)
        sys.exit(1)
    print(f"[cookie] {cmsg}", file=sys.stderr)

    dest = os.path.join(args.workdir, "video.mp4")
    ok, msg = download(bvid, result["cid"], dest, cookie)
    result["video_path"] = dest if ok else ""
    result["ok"] = ok
    result["diagnosis"] = msg
    print(f"[下载] {msg}", file=sys.stderr)

    _dump(result, args.out)
    if not ok:
        sys.exit(1)


def _dump(result: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
