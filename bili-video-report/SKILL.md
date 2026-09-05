---
name: bili-video-report
description: "把 B 站视频（科普/教程/课程，含多 P）转成 HTML 图文学习报告。当用户贴 B 站链接（BV号/av号/b23.tv短链）想「总结/提炼/学习这个视频」「没时间看完」「把课程存档」时使用。流程：公开 API 取元数据 → cookie+ffmpeg 下载 → 带时间戳转录 → 抽 18 帧 → 时间戳×关键帧对齐的双层 HTML 报告 → 归档 Obsidian。"
agent_created: true
---

# B 站视频 → HTML 图文学习报告

## 核心认知

B 站视频与小红书的分工：**xhs-video-report 打小红书，本 skill 打 B 站**，媒体管线同源。
但 B 站内容有两个本质差异，决定了本 skill 的两个增强：

1. **教程类画面信息占比远高于小红书**（代码演示、公式推导、架构图、数据榜单），
   口播会说"如图所示"但不会念图 → 默认抽帧从 10 张提到 **18 张**，且必须真看图。
2. **长视频多（20 分钟起步，多 P 课程上百集）** → 转录落盘 **segments.json（带时间戳）**，
   用「时间戳 × 关键帧对齐」让报告每个要点都能跳回原视频，这是本 skill 的灵魂。

**输出物是 HTML，不是 Markdown。** 模板见 `references/report-template.html`，
含时间轴导航、多 P 分 P 索引、降级告知三个 xhs 模板没有的组件。

## 抓取层：为什么不用 yt-dlp（重要，别凭直觉改回去）

实测（2026-09-05，yt-dlp 2026.08.19）：yt-dlp 走 `x/player/wbi/v2`，本机**稳定 412**；
而老接口 `x/player/playurl?fnval=16` 带 cookie 直接返回 `code 0`，**连 wbi 签名都不需要**。
所以抓取层是：

```
公开 API（view / player/v2）      → 元数据 + 分P列表，免登录免签名
bsk 导出浏览器 cookie（缓存复用）  → 23 条左右，document.cookie 能拿到的
playurl(fnval=16) 选流            → ≤720p 视频 + 最高码率音频
ffmpeg 双输入 -c copy             → 直接下 DASH 并合并，20 分钟视频约 5 秒 48MB
```

- cookie 缓存在 `~/.cache/bili-video-report/cookies.txt`，检测到 403/412 才重导
- **大会员/付费视频拿不到**：`SESSDATA` 是 HttpOnly，`document.cookie` 读不到 → 明确降级
- 字幕（`player/v2` 的 subtitle）5 条样本全空，拿到算彩蛋，拿不到是常态 → 转录是主路径

## 前置依赖

- Python 环境：`~//.workbuddy/binaries/python/envs/default/bin/python`
  （装有 `imageio-ffmpeg` + `mlx-whisper`；用错解释器会报 ModuleNotFoundError）
- `bsk`（`~/.local/bin/bsk`）：仅在导出 cookie 时用，浏览器需已登录 B 站
- 无 yt-dlp 依赖

环境体检：`$PY scripts/selfcheck.py`

## 工作流

```bash
PY=~//.workbuddy/binaries/python/envs/default/bin/python
cd ~/.workbuddy/skills/bili-video-report/scripts

# 1) 解析链接 → 元数据/分P → 下载（cookie 自动导出/复用）
$PY fetch_bili.py "<B站链接或BV号>" --workdir /tmp/bili_work
#    --pages 1-4 取多P（默认第1P）；--no-download 只看元数据；--refresh-cookie 重导

# 2) 抽音频 → 转录（落盘 segments.json）→ 抽 18 帧
#    多 P 时加 --page N，workdir 用 /tmp/bili_work/pN
$PY media.py --meta /tmp/bili_meta.json --workdir /tmp/bili_work --frames 18

# 3) 按 references/report-template.html 撰写报告，归档 Obsidian（见下）
```

产物：`video.mp4` / `audio.wav` / `transcript.txt` / `segments.json` / `frames/*.jpg` / `meta.json`。

**性能基准（M4，19分50秒视频）**：下载 5s（48MB）→ 转录 132s → 18 帧。
30 分钟内视频走全量；60 分钟约 8 分钟；3 小时约 25 分钟。

## 报告撰写规范

1. **双层结构**：速览卡（30 秒判断值不值得看，敢下判断、给星级）+ 深度笔记。
2. **时间轴导航必写**：用 `segments.json` 搜关键词定位真实时间戳，配对应帧的图。
   时间必须来自 segments，不许编。
3. **反直觉点 / 增量认知**是全片最值钱的一节，禁止复述视频内容。
4. **「与我何干」**必须引用用户真实项目（如 Agent 测评、AI 中台），不能空谈。
5. **ASR 纠错表**必填：天玑→天津、锁容→索容、大横评→大横屏 这类同音错要修。
6. **降级红线**：拿不到口播（下载失败/大会员/纯 BGM）必须保留模板里的红色
   降级告知块并说明原因，**不得伪装成"看过了"**。转录 <50 字或高度重复 = 无口播。

## 多 P 课程与长视频

- 多 P 是**一等公民**：`fetch_bili.py --pages 1-4 / all` 逐 P 下载（`p{N}.mp4`）并探字幕，
  meta.json 的 `items[]` 是 per-P 完整数据源（cid/part/duration/subtitle/video_path）。
  然后逐 P 跑媒体层：`media.py --meta <meta.json> --page N --workdir <dir>/pN`
- 报告 = 1 份**总索引页**（模板「分 P 索引」卡片，一 P 一张速览卡）
  + 每 P 一份单页报告。文件名 `{日期}-bili-{英文短名}-p{N}.html`。
- 长视频分块防上下文爆炸：`<30 分钟` 全量转录进上下文；`30–90 分钟` 按 segment
  分块逐块摘要再合并；`>90 分钟` 按 P 独立处理。
- 翻译腔多 P（日/英/韩配音版）实测会出现：转录多语言混杂，报告只精做中文 P，
  其余 P 在索引页标注语言与一句话结论即可，不必逐 P 深写。

## 归档约定（Obsidian）

```
~//Obsidian/AI技术/视频学习报告/{YYYY-MM-DD}-bili-{英文短名}.html
~//Obsidian/AI技术/视频学习报告/frames/{ASCII语义名}.jpg   # 如 bili_rank_chart.jpg
```

- 报告 HTML 内部用相对路径 `frames/xxx.jpg` 引图；**文件名一律 ASCII**，中文只出现在标题里。
- 帧只归档引用的（6 张左右），不搬全部 18 张。

## 踩坑清单（都踩过，别再踩）

1. `document.cookie` 拿不到 `SESSDATA`（HttpOnly）→ 大会员视频降级，别死磕。
2. media.py 的 `download()` 有本地文件分支，但 fetch_bili 已把视频下到
   `workdir/video.mp4`，src==dest 会抛 SameFileError → 已改为直接复用。
3. imageio 的 ffmpeg 二进制名带平台后缀，mlx-whisper 硬编码调 `ffmpeg` →
   media.py 已自动建软链加 PATH；fetch_bili 的 dash_download 单独处理。
4. 代理下 HF 502 → `HF_ENDPOINT=hf-mirror`；镜像 Xet 401 → `HF_HUB_DISABLE_XET=1`
   （media.py 已内置）。
5. `bsk evaluate --json` 的返回值在 `value` 键里，不在 `result`。
6. 用错 Python（没装 imageio_ffmpeg/mlx_whisper 的解释器）→ ModuleNotFoundError，
   固定用上面 `PY` 指的那个环境。
