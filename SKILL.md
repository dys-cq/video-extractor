---
name: video-extractor
description: "Extract video transcripts, articles, comments, and text/image content from platforms including Douyin, Bilibili, YouTube, XiaoHongShu, WeChat Channels (微信视频号), WeChat Official Accounts (微信公众号), X/Twitter, Zhihu (知乎), and Xiaoyuzhou podcasts. Handles video, image-text, article, and text-only posts. Uses Whisper large-v3-turbo for native Simplified Chinese output. Supports batch downloads, resume, progress reports, and YouTube Invidious fallback. Triggers: \"提取文案\", \"提取评论\", \"视频转录\", \"video transcript\", \"extract comments\", \"video analysis\", \"播客转录\", \"小宇宙\", \"xiaoyuzhou\", \"下载视频\", \"video download\", \"提取推文\", \"twitter\", \"知乎\", \"zhihu\", \"公众号\", \"wechat\", \"本地视频\", \"逐字稿\", \"转文字\"."
---

# Video Extractor

Extract transcripts, download videos, and extract content from video and social platforms (Douyin, Bilibili, YouTube, XiaoHongShu, WeChat Channels / 微信视频号, X/Twitter, Zhihu, etc.). Also supports Xiaoyuzhou (小宇宙) podcast extraction.

## Overview

Three main tasks:
1. **Video / content download**: Platform-specific best method — yt-dlp for YouTube/Xiaohongshu/Bilibili (with cookies), direct API for Bilibili audio, Playwright for anti-bot platforms (Douyin/X/Zhihu), online parser for WeChat Channels
2. **Transcript extraction**: `ffmpeg` (audio extraction) + `whisper` (speech-to-text)
3. **Content extraction**: Text + images for image-text posts (X/Twitter, Zhihu, Xiaohongshu, WeChat Official Accounts)

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| `yt-dlp` | Download from YouTube, Bilibili (with cookies), Xiaohongshu | `pip install yt-dlp` |
| `playwright` | Extraction from anti-bot platforms (Douyin, X, Zhihu, Xiaohongshu) | `pip install playwright && python -m playwright install chromium` |
| `openai-whisper` | Speech-to-text transcription | `pip install openai-whisper` |
| `requests` | Direct HTTP downloads (WeChat Channels, API fallbacks) | `pip install requests` |
| `ffmpeg` | Audio processing (whisper dependency) | System package |

**Check before starting:** `yt-dlp --version`, `python -c "import whisper"`, `python -c "import playwright"`

---

## Project Root & Output Directory Structure

### Project Root Discovery

**Determine output root in this priority order:**

1. **`OUTPUT_ROOT` environment variable** — if set and non-empty, use it as the base
2. **Fallback**: `{workspace}/Outputs/` (relative to current working directory)

### Helper function pattern (Python)

```python
import os
from pathlib import Path
import datetime as dt

def get_output_root() -> Path:
    """Resolve output root directory.
    Priority: OUTPUT_ROOT env var > workspace/Outputs/
    """
    env_root = os.environ.get("OUTPUT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.cwd() / "Outputs"

def make_run_dir(title: str, topic: str = "") -> Path:
    """Create a dated output directory.
    Returns: {output_root}/YYYY-MM-DD-{slug}/
    If title is empty, uses the platform name as fallback.
    """
    root = get_output_root()
    date = dt.date.today().isoformat()
    slug = title or "video-download"
    candidate = root / f"{date}-{slug}"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate
```

### Output Directory Structure

```
{output_root}/YYYY-MM-DD-{topic_or_source}/
├── {author}_《{title}》.mp4                # Video file (H.264)
├── {author}_《{title}》_video_h265.mp4    # Optional: H.265 version (WeChat Channels)
├── {author}_《{title}》.wav                # Extracted audio (WAV, 16kHz mono)
├── {author}_《{title}》_逐字稿.md           # Final transcript with timestamps + metadata
├── download-report.md                      # Task report (success/failure counts, file sizes)
├── download-report.json                    # Machine-readable task report
├── .metadata.json                          # Raw source metadata (author, title, URL, etc.)
└── README.md                               # Optional: index of all files in this folder
```

### Naming Rules

**NEVER use generic names like `audio.txt`, `transcript.txt`, `weixin_video_transcription.txt`.**

| Scenario | Pattern | Example |
|----------|---------|---------|
| Video with title/author | `{Author}_《{Title}》.{suffix}` | `张咋啦Zara_《四个AI原生工作方式》.mp4` |
| Xiaoyuzhou podcast | `{PodcastName}_《{EpisodeTitle}》.{suffix}` | `小宇宙_《AI时代的个人效率》.md` |
| Bilibili video | `{Bvid}_《{Title}》.{suffix}` | `BV1xx__《如何学习新技术》.txt` |
| No metadata available | `{Domain}_{Slug}.{suffix}` | `weixin.qq_com_Ai0Bh80uel.txt` |

### Workspace Layout

```
{workspace}/
├── .python_cache/                  # Model cache, Python venv (NOT in Outputs)
├── .scripts/                       # Temp scripts for current tasks
│   ├── bili_download.py
│   ├── douyin_extract.py
│   └── ...
└── Outputs/                        # All deliverables only
    └── 2026-08-03-AI工具教程/
        ├── 张咋啦Zara_《白板视频》/
        │   ├── *.mp4 / *.wav / *.md
        └── 技术爬爬虾_《Follow聚合神器》/
            ├── *.mp4 / *.wav / *.md
```

**Rules:**
- **One day, one top-level directory** — all tasks from the same day go under `YYYY-MM-DD-{topic}/`
- **Multiple videos in same day** → each gets its own subfolder: `{video_title}/`
- **Temp scripts go in `.scripts/`**, NEVER in `Outputs/`
- **Outputs directory only contains deliverables** — no code, no temp data

---

## Task Report (download-report.md + .json)

**Every task must generate a report.**

### Report Generation Template

```python
import json
import datetime as dt
from pathlib import Path

def write_reports(out_dir: Path, urls: list[str], records: list[dict]) -> None:
    """Generate both JSON and Markdown reports."""
    payload = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "out_dir": str(out_dir),
        "urls": urls,
        "records": records,
    }
    (out_dir / "download-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ok = sum(1 for r in records if r["status"] == "ok")
    skipped = sum(1 for r in records if r["status"] == "skipped")
    failed = len(records) - ok - skipped

    lines = [
        "# 视频处理报告", "",
        f"- **输出目录**：`{out_dir}`",
        f"- **链接数量**：{len(records)}",
        f"- **成功**：{ok}",
        f"- **已跳过**：{skipped}",
        f"- **失败**：{failed}", "",
        "| 状态 | 类型 | 平台 | 文件 | 大小 | 链接 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        files = "<br>".join(f"`{Path(p).name}`" for p in r.get("files", []))
        lines.append(
            "| " + " | ".join([
                r.get("status", ""),
                r.get("kind", ""),
                r.get("platform", ""),
                files or "",
                _size_text(r.get("bytes", 0)),
                f"<{r.get('url', '')}>",
                r.get("note", "").replace("|", "\\|"),
            ]) + " |"
        )
    (out_dir / "download-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

def _size_text(n: int) -> str:
    if not n:
        return ""
    units = ["B", "KB", "MB", "GB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.1f} {u}" if u != "B" else f"{int(v)} B"
        v /= 1024
    return f"{n} B"
```

### Record structure

```python
{
    "url": "https://...",
    "kind": "platform|direct|wx-channels|stream|image-text",
    "platform": "Bilibili|Douyin|YouTube|WeixinChannels|Xiaohongshu|X/Twitter|Zhihu",
    "status": "ok|skipped|failed",
    "files": ["path/to/file1.mp4", ...],
    "bytes": 12345678,
    "note": "reason for failure or extra info",
}
```

---

## Resume & Download History

### Direct Video Resume (.part files)

For direct HTTP downloads, support resuming with HTTP Range:

```python
def download_with_resume(url: str, target: Path, *, headers: dict = None,
                          timeout: int = 120, max_mb: float = 2000) -> dict:
    """Download with resume support using .part file."""
    partial = Path(str(target) + ".part")
    resume_from = partial.stat().st_size if partial.exists() else 0
    mode = "ab" if resume_from else "wb"
    
    req_headers = dict(headers or {})
    if resume_from:
        req_headers["Range"] = f"bytes={resume_from}-"
    
    resp = requests.get(url, headers=req_headers, stream=True, timeout=timeout)
    
    if resume_from and resp.status_code == 206:
        pass  # Server supports range
    elif resume_from and resp.status_code == 200:
        resume_from = 0
        mode = "wb"
    else:
        resp.raise_for_status()
    
    limit = int(max_mb * 1024 * 1024)
    size = resume_from
    with open(partial, mode) as f:
        for chunk in resp.iter_content(1024 * 64):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                partial.unlink(missing_ok=True)
                return {"status": "failed", "note": f"video-larger-than-{max_mb:g}MB"}
            f.write(chunk)
    
    partial.replace(target)
    return {"status": "ok", "bytes": size, "files": [str(target)]}
```

### Download Archive (avoid re-downloading)

For batch / playlist tasks, use a download archive file:

```python
ARCHIVE_FILE = "download-archive.txt"

def already_downloaded(identifier: str) -> bool:
    if not Path(ARCHIVE_FILE).exists():
        return False
    with open(ARCHIVE_FILE, "r") as f:
        return identifier in f.read()

def mark_downloaded(identifier: str):
    with open(ARCHIVE_FILE, "a") as f:
        f.write(identifier + "\n")
```

Usage:
```python
for url in urls:
    vid = extract_video_id(url)
    if already_downloaded(f"{platform} {vid}"):
        records.append({"status": "skipped", "note": "already in archive"})
        continue
    # ... download ...
    mark_downloaded(f"{platform} {vid}")
```

---

## Platform Method Priority Matrix

| Platform | Primary Method | Fallback | Notes |
|----------|---------------|----------|-------|
| **YouTube** | yt-dlp | Invidious proxy (360p) | yt-dlp works great |
| **Bilibili** | Direct playurl API (audio) | yt-dlp + cookies (HD video) | yt-dlp usually 412; API works without cookies |
| **WeChat Channels** | Online parser (`sph.litao.workers.dev`) | None known | No login needed |
| **WeChat Official Accounts** | Direct HTTP request | None needed | Surprisingly easy — full article without login |
| **Xiaohongshu** | yt-dlp (works well!) | Playwright (for text metadata) | Surprisingly good yt-dlp support |
| **Douyin** | Playwright API interception | yt-dlp + login cookies | yt-dlp almost always fails |
| **X/Twitter** | Playwright | yt-dlp + login cookies | yt-dlp unreliable without login |
| **Zhihu** | Playwright (non-headless + stealth) | Direct API (usually 403) | Headless Playwright easily detected |
| **Xiaoyuzhou** | Direct HTTP download | None | Podcast audio is publicly accessible |

---

## Task 0: WeChat Channels (微信视频号) Extraction

When the URL contains `weixin.qq.com/sph/`, this is a WeChat Channels task.

### Method: Online Parsing Service

Uses `https://sph.litao.workers.dev/api/fetch_video_profile` to resolve share links into actual video URLs (H.264 + H.265 versions).

**Pros:** No login needed, works on all platforms.
**Credit:** [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download)

### Workflow

```python
import requests

WX_API = "https://sph.litao.workers.dev/api/fetch_video_profile"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def fetch_wx_channels(url: str, out_dir: Path, *, max_mb: float = 2000) -> dict:
    record = base_record(url, "wx-channels")
    record["platform"] = "WeixinChannels"
    
    # Parse
    resp = requests.post(WX_API, json={"url": url},
                        headers={"Content-Type": "application/json", "User-Agent": UA},
                        timeout=30)
    if resp.status_code != 200:
        record["note"] = f"parse-http-{resp.status_code}"
        return record
    
    data = resp.json()
    if data.get("errCode") and data.get("errCode") != 0:
        record["note"] = f"parse-error: {data.get('errMsg', 'unknown')}"
        return record
    
    feed = data["data"]["feedInfo"]
    author = data["data"]["authorInfo"]["nickname"]
    desc = feed.get("description", "").strip()[:80]
    h264_url = feed.get("h264VideoInfo", {}).get("videoUrl", "")
    h265_url = feed.get("h265VideoInfo", {}).get("videoUrl", "")
    
    # Download both versions
    downloaded = []
    total_bytes = 0
    for video_url, label in [(h264_url, "H264"), (h265_url, "H265")]:
        if not video_url:
            continue
        filename = f"{_safe_filename(desc or author)}_video{'_' + label if label == 'H265' else ''}.mp4"
        target = out_dir / filename
        dl_result = download_with_resume(
            video_url, target,
            headers={"User-Agent": UA, "Referer": "https://weixin.qq.com/"},
            max_mb=max_mb,
        )
        if dl_result["status"] == "ok":
            downloaded.extend(dl_result["files"])
            total_bytes += dl_result["bytes"]
    
    if downloaded:
        record["status"] = "ok"
        record["files"] = downloaded
        record["bytes"] = total_bytes
    
    (out_dir / ".metadata.json").write_text(
        json.dumps(data["data"], ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return record
```

---

## Task 0a: WeChat Official Account (微信公众号) Article Extraction

When the URL contains `mp.weixin.qq.com/s/`, this is a WeChat article extraction task.

### Method: 3-Tier Fallback

| Tier | Method | Use when | Notes |
|------|--------|----------|-------|
| 1 | Direct HTTP request | Most public articles | Fastest, no browser needed |
| 2 | Playwright non-headless + stealth | Tier 1 blocked by "环境异常" verification | Opens a real browser window |
| 3 | CDP connection (Chrome port 9222) | Tier 2 also fails | Reuses user's logged-in browser |

**Tier 1: Direct HTTP Request (PRIMARY)**

```python
import requests, re

WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

r = requests.get(url, headers=WX_HEADERS, timeout=30)
html = r.text
```

**Tier 2: Playwright (for verification-blocked articles)**

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,  # Non-headless REQUIRED
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
    )
    context = browser.new_context(
        user_agent=WX_HEADERS["User-Agent"],
        viewport={"width": 1280, "height": 900}, locale="zh-CN",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        window.chrome = {runtime: {}};
    """)
    page = context.new_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
```

**Tier 3: CDP (reuse user's logged-in Chrome)**

Requires Chrome running with `--remote-debugging-port=9222`. Then:
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()
    # ... same extraction logic ...
    page.close()
    browser.close()  # disconnects only, does NOT close user's Chrome
```

### Key Extraction Notes

- **Title**: `#activity-name` element, or `og:title` meta
- **Author**: iterate `[class*="nickname"]` elements, take first non-empty text (≤20 chars). The first match (`input_nickname`) is often empty — must iterate!
- **Publish time**: JS var `var ct = "unix_timestamp"`
- **Content**: `#js_content` div (also works for image-message articles)
- **Images — 3 sources, in priority order**:
  1. `<img>` tags in content: `data-src` attribute (lazy loading)
  2. **`<ol> <li>` background-image** (image-message / swiper articles!): the body images are CSS `background-image` on `li` elements inside an `ol`, NOT `<img>` tags. URLs look like `/300?wx_fmt=png` (thumbnail) — replace `/300?` with `/0?` to get original size, strip `&from=appmsg&wxfrom=N`
  3. `og:image` meta (cover, only if no other images found)
- **Image download**: needs `Referer: https://mp.weixin.qq.com/` header
- **Image format**: append `wx_fmt=jpeg` to URL for consistent JPEG
- **Verification detection**: page text contains "环境异常" / "完成验证" / "验证码"
- **Filename**: `{author}_《{title}》_公众号文章.md`

### Workflow

```
Given mp.weixin.qq.com/s/ URL
   |
   v
Tier 1: requests.get() → content found? → YES → Done
   |
   NO (verification page)
   |
   v
Tier 2: Playwright non-headless → content found? → YES → Done
   |
   NO
   |
   v
Tier 3: CDP connect to user's Chrome (port 9222) → content found? → YES → Done
   |
   v
Failed: report "article may require login"
```

### Pitfalls

1. **First nickname element is empty** (`input_nickname` class) — must iterate all matches
2. **Image-message articles: body images are CSS background-image on `ol > li`**, NOT `<img>` tags — must scan `getComputedStyle(li).backgroundImage`. The `<ol>` is the swiper indicator; each `li` shows one image. URLs have `/300` thumbnail suffix — convert to `/0` for originals
3. **Network-level image capture catches junk** — 17 URLs captured but only 7 are body images (rest are avatars/icons); DOM background-image extraction is precise
4. **Verification is per-request** — may pass once, fail next time; retry with browser
5. **Jina AI reader (`r.jina.ai/`) does NOT work** for WeChat — it hits the same verification wall
6. **Persistent context with user's Chrome profile fails** if Chrome is running (profile locked) — use CDP instead
7. **Tier 3 requires user to launch Chrome with debug port** — explain clearly, don't auto-restart their browser

---

## Task 1: Bilibili (B站) Video & Audio Download

### Method 1: Direct Playurl API (PRIMARY — no cookies needed)

Use `/x/player/playurl` API directly. Only 32p/16p video but **audio quality is unaffected** (up to 162kbps), sufficient for transcription.

```python
import requests, subprocess

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}

def get_bili_audio(bvid: str, output_wav: str, ffmpeg: str = "ffmpeg") -> tuple:
    """Download highest-quality audio from Bilibili (no cookies needed)."""
    # Get cid and metadata
    view = requests.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                       headers=HEADERS, timeout=15).json()
    cid = view["data"]["cid"]
    title = view["data"]["title"]
    owner = view["data"]["owner"]["name"]
    
    # Get DASH audio URL
    play = requests.get(
        f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&fourk=1",
        headers=HEADERS, timeout=15,
    ).json()
    best = sorted(play["data"]["dash"]["audio"], key=lambda x: x["bandwidth"], reverse=True)[0]
    
    # Download m4s audio
    resp = requests.get(best["baseUrl"], headers=HEADERS, stream=True, timeout=120)
    temp_m4s = output_wav + ".m4s"
    with open(temp_m4s, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    
    # Convert to WAV
    subprocess.run([
        ffmpeg, "-y", "-i", temp_m4s,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_wav,
    ], check=True, capture_output=True)
    
    os.unlink(temp_m4s)
    return True, title, owner
```

### Method 2: yt-dlp (with cookies — HD video)

```bash
yt-dlp -f "bv*+ba/b" --cookies cookies.txt \
  -o "{out_dir}/%(title)s.%(ext)s" \
  "https://www.bilibili.com/video/BV1xxxxx"
```

---

## Task 2: Douyin (抖音) Video & Audio Extraction

Douyin has strong anti-bot protection. Direct API calls and HTML scraping both fail.

### Method: Playwright API Interception (PRIMARY)

Launch a real browser, intercept the `aweme/detail` XHR response, extract the video URL.

```python
from playwright.sync_api import sync_playwright

def download_douyin(short_url: str, out_dir: Path) -> dict:
    record = {"url": short_url, "kind": "douyin", "platform": "Douyin",
              "status": "failed", "files": [], "bytes": 0, "note": ""}
    video_url = None
    author = ""
    title = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 720},
        )
        
        def handle_response(resp):
            nonlocal video_url, author, title
            if "aweme" in resp.url and "detail" in resp.url:
                try:
                    data = resp.json()
                    detail = data.get("aweme_detail", {})
                    if detail:
                        title = (detail.get("desc") or "").strip()[:80]
                        author = detail.get("author", {}).get("nickname", "")
                        urls = detail.get("video", {}).get("play_addr", {}).get("url_list", [])
                        if urls:
                            video_url = urls[0]
                except:
                    pass
        
        page = context.new_page()
        page.on("response", handle_response)
        page.goto(short_url, timeout=30000)
        page.wait_for_timeout(5000)
        
        # Fallback: video element
        if not video_url:
            for v in page.query_selector_all("video"):
                src = v.get_attribute("src")
                if src and ".mp4" in src:
                    video_url = src
                    break
        
        browser.close()
    
    if not video_url:
        record["note"] = "video-url-not-found"
        return record
    
    # Download video
    title_safe = _safe_filename(title or "douyin-video")
    target = out_dir / f"{_safe_filename(author)}_《{title_safe}》_video.mp4"
    resp = requests.get(video_url,
                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/"},
                       stream=True, timeout=120)
    size = 0
    with open(target, "wb") as f:
        for chunk in resp.iter_content(64*1024):
            if chunk:
                f.write(chunk)
                size += len(chunk)
    
    record["status"] = "ok"
    record["files"] = [str(target)]
    record["bytes"] = size
    record["note"] = "Playwright API interception"
    (out_dir / ".metadata.json").write_text(
        json.dumps({"author": author, "title": title, "url": short_url},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return record
```

---

## Task 2a: X/Twitter Extraction

Supports **video tweets**, **image/text tweets**, and **text-only tweets**.

### Detection

| Tweet type | How to detect | Extraction method |
|------------|--------------|-------------------|
| Video | `video.twimg.com` in response, `<video>` element | Download MP4 + transcribe |
| Image/GIF | `pbs.twimg.com/media/` URLs, `<img>` elements | Download images + optional OCR |
| Text-only | No media found | Save tweet text as markdown |

### Method: Playwright (PRIMARY)

yt-dlp is unreliable for X without cookies. Use Playwright as primary method.

```python
from playwright.sync_api import sync_playwright

def extract_twitter(url: str, out_dir: Path) -> dict:
    record = {"url": url, "kind": "x-twitter", "platform": "X/Twitter",
              "status": "failed", "files": [], "bytes": 0, "note": ""}
    video_url = None
    tweet_text = ""
    author = ""
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 720},
        )
        
        def handle_response(resp):
            nonlocal video_url
            u = resp.url
            if 'video.twimg.com' in u and '.mp4' in u and not video_url:
                video_url = u
        
        page = context.new_page()
        page.on("response", handle_response)
        page.goto(url, timeout=30000)
        page.wait_for_timeout(5000)
        
        # Tweet text + author
        article = page.query_selector("article")
        if article:
            tweet_text = article.inner_text()
        name_el = page.query_selector("[data-testid='User-Name']")
        if name_el:
            author = name_el.inner_text().split('\n')[0].strip()
        
        # Images
        image_urls = []
        for img in page.query_selector_all("img"):
            src = img.get_attribute("src") or ""
            if "pbs.twimg.com/media/" in src:
                if "?format=" not in src:
                    src += "?format=jpg&name=orig"
                image_urls.append(src)
        
        browser.close()
    
    # Download video or images
    if video_url:
        record["kind"] = "x-twitter-video"
        target = out_dir / "video.mp4"
        r = requests.get(video_url, headers={"User-Agent": "Mozilla/5.0"},
                        stream=True, timeout=120)
        size = 0
        with open(target, "wb") as f:
            for chunk in r.iter_content(64*1024):
                if chunk:
                    f.write(chunk)
                    size += len(chunk)
        record["status"] = "ok"
        record["files"] = [str(target)]
        record["bytes"] = size
    elif image_urls:
        record["kind"] = "x-twitter-image"
        downloaded = []
        for i, img_url in enumerate(image_urls, 1):
            target = out_dir / f"image_{i}.jpg"
            r = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                target.write_bytes(r.content)
                downloaded.append(str(target))
        if downloaded:
            record["status"] = "ok"
            record["files"] = downloaded
            record["bytes"] = sum(Path(f).stat().st_size for f in downloaded)
            record["note"] = f"{len(downloaded)} images"
    else:
        record["kind"] = "x-twitter-text"
    
    # Always save tweet text as markdown
    if tweet_text:
        md_path = out_dir / f"{_safe_filename(author or 'twitter')}_《{_safe_filename(tweet_text[:30])}》_推文内容.md"
        md_content = f"""# Tweet Content

- **Author**: @{author}
- **Source**: <{url}>
- **Platform**: X / Twitter
- **Extracted**: {dt.datetime.now().isoformat(timespec='seconds')}

---

{tweet_text}
"""
        md_path.write_text(md_content, encoding="utf-8")
        record["files"].append(str(md_path))
        if record["status"] != "ok":
            record["status"] = "ok"
            record["note"] = "text-only"
    
    (out_dir / ".metadata.json").write_text(
        json.dumps({"author": author, "tweet_text": tweet_text, "url": url},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return record
```

### OCR for Image Tweets (Optional)

Only do OCR if user explicitly asks for it.

```bash
pip install easyocr
```

```python
import easyocr
reader = easyocr.Reader(['ch_sim', 'en'])
result = reader.readtext('image_1.jpg')
```

---

## Task 2b: Zhihu (知乎) Answer/Article Extraction

Zhihu has strong anti-bot protection. Direct API returns 403, headless Playwright is often detected.

### Method: Non-headless Playwright + stealth scripts (PRIMARY)

```python
from playwright.sync_api import sync_playwright

def extract_zhihu(url: str, out_dir: Path) -> dict:
    record = {"url": url, "kind": "zhihu-answer", "platform": "Zhihu",
              "status": "failed", "files": [], "bytes": 0, "note": ""}
    title = ""
    author = ""
    content_text = ""
    content_html = ""
    image_urls = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # CRITICAL: non-headless bypasses detection
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            window.chrome = {runtime: {}};
        """)
        
        page = context.new_page()
        # Warm up cookies first
        try:
            page.goto("https://www.zhihu.com/", timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
        except:
            pass
        
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        
        # Title
        for sel in [".QuestionHeader-title", "[class*='QuestionHeader-title']", "h1"]:
            el = page.query_selector(sel)
            if el and el.inner_text().strip():
                title = el.inner_text().strip()
                break
        
        # Content
        for sel in [".RichContent-inner", "[class*='RichText']", ".Post-RichText", "article"]:
            el = page.query_selector(sel)
            if el and len(el.inner_text()) > 100:
                content_text = el.inner_text()
                content_html = el.inner_html()
                break
        
        # Author
        for sel in [".AuthorInfo-name a", "[class*='AuthorInfo']", ".UserLink-link"]:
            el = page.query_selector(sel)
            if el:
                author = el.inner_text().strip().split('\n')[0].strip()
                break
        
        # Images (extract from HTML for high quality)
        if content_html:
            img_matches = re.findall(r'<img[^>]+(?:data-original|data-src|src)="([^"]+)"', content_html)
            for src in img_matches:
                if src and src.startswith("http") and "zhimg" in src:
                    base = src.split('?')[0]
                    for s in ['_b.', '_s.', '_xl.']:
                        if s in base:
                            base = base.replace(s, '_r.')
                            break
                    if not base.endswith(('.jpg', '.png', '.gif')):
                        base += '.jpg'
                    if base not in image_urls:
                        image_urls.append(base)
        
        browser.close()
    
    if not content_text:
        record["note"] = "content-not-found"
        return record
    
    # Download images
    downloaded = []
    for i, img_url in enumerate(image_urls, 1):
        target = out_dir / f"image_{i}.jpg"
        try:
            r = requests.get(img_url, headers={
                "User-Agent": "Mozilla/5.0", "Referer": "https://www.zhihu.com/",
            }, timeout=30, stream=True)
            if r.status_code == 200:
                size = 0
                with open(target, "wb") as f:
                    for chunk in r.iter_content(64*1024):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size > 2000:
                    downloaded.append(str(target))
        except:
            continue
    
    # Save as Markdown
    title_safe = _safe_filename(title[:50] or "zhihu")
    author_safe = _safe_filename(author or "zhihu")
    md_path = out_dir / f"{author_safe}_《{title_safe}》_知乎回答.md"
    md_content = f"""# {title}

## 元数据
- **作者**：{author}
- **来源**：<{url}>
- **平台**：知乎
- **图片数**：{len(downloaded)}
- **提取时间**：{dt.datetime.now().isoformat(timespec='seconds')}

---

## 正文

{content_text}

---

## 图片

"""
    for i, img in enumerate(downloaded, 1):
        md_content += f"### 图片 {i}\n\n![image_{i}]({Path(img).name})\n\n"
    md_path.write_text(md_content, encoding="utf-8")
    
    record["status"] = "ok"
    record["files"] = [str(md_path)] + downloaded
    record["bytes"] = sum(Path(f).stat().st_size for f in [str(md_path)] + downloaded if Path(f).exists())
    record["note"] = f"{len(content_text)}字, {len(downloaded)}图"
    
    (out_dir / ".metadata.json").write_text(
        json.dumps({"author": author, "title": title, "url": url,
                    "word_count": len(content_text), "image_count": len(downloaded)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return record
```

### Image URL quality variants

Zhihu CDN serves different quality versions:
- `_s.jpg` = small thumbnail
- `_b.jpg` = big (~720p)
- `_r.jpg` = **raw / original quality** ← always use this
- `_xl.jpg` = extra large

---

## Task 3: YouTube Video Download

### Method 1: yt-dlp (PRIMARY)

```bash
yt-dlp -f "bv*+ba/b" -o "{out_dir}/%(title)s [%(id)s].%(ext)s" "YOUTUBE_URL"
```

### Method 2: Invidious Proxy Fallback

If yt-dlp is blocked by bot verification/login checks, fall back to an Invidious proxy. Downloads a 360p progressive MP4 (itag=18).

```python
INVIDIOUS_INSTANCES = ("https://inv.thepixora.com",)
FALLBACK_ITAG = "18"  # 360p MP4

def youtube_invidious_fallback(url: str, out_dir: Path) -> dict:
    record = {"url": url, "kind": "youtube-invidious", "platform": "YouTube / Invidious",
              "status": "failed", "files": [], "bytes": 0, "note": ""}
    video_id = extract_youtube_id(url)
    if not video_id:
        record["note"] = "youtube-id-not-found"
        return record
    
    for instance in INVIDIOUS_INSTANCES:
        instance = instance.rstrip("/")
        try:
            api = requests.get(f"{instance}/api/v1/videos/{video_id}",
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()
            title = api.get("title", "youtube-video")
            target = out_dir / f"{_safe_filename(title[:60])} [{video_id}]-360p.mp4"
            
            # Resolve proxy URL (two redirects)
            latest = f"{instance}/latest_version?id={video_id}&itag={FALLBACK_ITAG}&local=true"
            r1 = requests.get(latest, allow_redirects=False, timeout=30)
            loc = r1.headers.get("Location", "")
            if loc.startswith("/"):
                loc = instance + loc
            r2 = requests.get(loc, allow_redirects=False, timeout=30)
            proxy_url = r2.headers.get("Location", "")
            if proxy_url.startswith("/"):
                proxy_url = instance + proxy_url
            
            # Download
            resp = requests.get(proxy_url, headers={"User-Agent": "Mozilla/5.0"},
                               stream=True, timeout=120)
            size = 0
            with open(target, "wb") as f:
                for chunk in resp.iter_content(64*1024):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
            
            record["status"] = "ok"
            record["files"] = [str(target)]
            record["bytes"] = size
            record["note"] = f"via {instance} itag={FALLBACK_ITAG}"
            return record
        except Exception as e:
            last_error = f"{instance}: {str(e)[:100]}"
            continue
    
    record["note"] = f"invidious-fallback-failed"
    return record
```

**Important:** Only use Invidious fallback if yt-dlp fails AND it looks like a cookie/login issue.

---

## Task 3a: Xiaohongshu (小红书) Extraction

**Surprisingly, yt-dlp works great for Xiaohongshu!** Downloads video at full speed.

### Method 1: yt-dlp (PRIMARY)

```python
import yt_dlp

def download_xhs(url: str, out_dir: Path) -> dict:
    """Download Xiaohongshu content via yt-dlp.
    Works for both video and image-text notes (image-text = video slideshow)."""
    ydl_opts = {
        "outtmpl": str(out_dir / "%(title).60s.%(ext)s"),
        "format": "best",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        # Resolve actual file
        base = Path(filepath).stem
        for m in out_dir.glob(f"{base}*"):
            if m.suffix.lower() in (".mp4", ".mkv", ".webm"):
                filepath = str(m)
                break
    
    return {
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration", 0),
        "filepath": filepath,
        "filesize": Path(filepath).stat().st_size,
    }
```

### Method 2: Playwright (for text metadata + images)

yt-dlp may not capture all text metadata for image-text notes. Use Playwright to get the full description:

```python
from playwright.sync_api import sync_playwright

def extract_xhs_metadata(url: str) -> dict:
    result = {"title": "", "description": "", "author": ""}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(user_agent="Mozilla/5.0", locale="zh-CN")
        page = context.new_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        title_el = page.query_selector("#detail-title") or page.query_selector(".note-title")
        if title_el:
            result["title"] = title_el.inner_text().strip()
        
        desc_el = page.query_selector("#detail-desc") or page.query_selector(".note-desc")
        if desc_el:
            result["description"] = desc_el.inner_text().strip()
        
        author_el = page.query_selector(".author-name") or page.query_selector(".user-name")
        if author_el:
            result["author"] = author_el.inner_text().strip().split('\n')[0]
        
        browser.close()
    
    return result
```

### Content Types

| Type | yt-dlp behavior | Playwright needed? |
|------|----------------|-------------------|
| Video note | Downloads MP4 directly | Optional (metadata) |
| Image-text note | Downloads as MP4 slideshow | Yes (for text + individual images) |

---

## Task 4: Whisper Transcription

### Model Selection

| Model | Chinese Output | Accuracy | Speed (RTX 3080) | Use Case |
|-------|--------------|----------|------------------|----------|
| `tiny/base/small` | Traditional Chinese biased | Low | Very Fast (~5x) | Quick previews only |
| `large-v3-turbo` | **Native Simplified Chinese** | High | Fast (~10x realtime) | ✅ **RECOMMENDED** |

### Basic Transcription

```python
import os
os.environ["WHISPER_NO_WSL"] = "1"  # MUST be BEFORE import whisper
import whisper

model = whisper.load_model("large-v3-turbo")
# Always pass string path, NOT Path object (Whisper crashes with Path)
result = model.transcribe(str(audio_path), task="transcribe", language="zh",
                          condition_on_previous_text=False)
```

### Standard Transcript Format (ALL platforms)

All transcripts use **identical format** for consistency:

```markdown
# 逐字稿

## 元数据
- **标题**：{title}
- **作者**：{author}
- **来源**：<{url}>
- **平台**：{platform}
- **语言**：{zh/en/...}
- **时长**：{mm:ss}
- **生成时间**：{YYYY-MM-DD}

---

[00:00 - 00:03] 第一段文字内容
[00:03 - 00:07] 第二段文字内容
...
```

**Rules:**
1. **Always Chinese headers** — metadata fields are always in Chinese
2. **Content language stays as-is** — if Whisper outputs English, keep it English
3. **Timestamp format: `[MM:SS - MM:SS]`** — for videos under 1 hour
4. **7 standard fields** in fixed order: 标题, 作者, 来源, 平台, 语言, 时长, 生成时间
5. **Filename:** `{author}_《{title}》_逐字稿.md`

### Long Audio (>30 min) — Anti-Hallucination

Split into 10-minute segments, transcribe each, detect hallucinated segments:

```python
from collections import Counter

def detect_hallucination(text: str) -> bool:
    """Check if >50% of non-empty lines are identical (= hallucination)."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) < 3:
        return False
    counter = Counter(lines)
    return counter.most_common(1)[0][1] / len(lines) > 0.5
```

**Timestamp Offset Fix:** Chunk N's timestamps start from 0, add `N * 600` seconds.
Use `scripts/merge_chunks.py` for automatic correction.

---

## Task 4a: 本地视频/音频文件转录

When the user provides a local file (`.mp4`, `.mkv`, `.avi`, `.wav`, `.mp3`, `.m4a`, `.flac`, etc.) and asks for a transcript, use this direct workflow — no download needed.

### Detection

If the input is a file path (not a URL) and the file exists, treat it as a local media transcription task.

**Trigger phrases:** "转录这个视频", "给这个视频做逐字稿", "转文字", "transcribe this file", "本地视频转录"

### Workflow

```python
import os
os.environ["WHISPER_NO_WSL"] = "1"
import subprocess
import whisper
import datetime as dt
from pathlib import Path

def transcribe_local_file(
    input_path: str,
    out_dir: Path,
    *,
    title: str = "",
    author: str = "",
    platform: str = "本地文件",
    source_url: str = "",
    model_name: str = "large-v3-turbo",
) -> dict:
    """Transcribe a local video/audio file.
    Returns a record dict compatible with download-report format.
    """
    record = {
        "url": source_url or str(input_path),
        "kind": "local-media",
        "platform": platform,
        "status": "failed",
        "files": [],
        "bytes": 0,
        "note": "",
    }
    
    input_path = Path(input_path)
    if not input_path.exists():
        record["note"] = f"file-not-found: {input_path}"
        return record
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Extract / convert audio to 16kHz mono WAV
    wav_path = out_dir / f"{_safe_filename(author or 'local')}_《{_safe_filename(title or input_path.stem)}》.wav"
    
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
         str(wav_path)],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        record["note"] = f"ffmpeg-error: {result.stderr[-200:]}"
        return record
    
    # Step 2: Get duration from WAV size (16kHz * 16bit * mono = 32000 bytes/sec)
    duration_sec = wav_path.stat().st_size // 32000
    
    # Step 3: Whisper transcription
    model = whisper.load_model(model_name)
    result_whisper = model.transcribe(
        str(wav_path),
        task="transcribe",
        language="zh",
        condition_on_previous_text=False,
    )
    
    # Step 4: Generate standard transcript format
    def _fmt(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    title_display = title or input_path.stem
    author_display = author or "未知"
    duration_str = _fmt(duration_sec)
    
    lines = [
        "# 逐字稿", "",
        "## 元数据",
        f"- **标题**：{title_display}",
        f"- **作者**：{author_display}",
        f"- **来源**：<{source_url}>" if source_url else f"- **来源**：{input_path.name}",
        f"- **平台**：{platform}",
        f"- **语言**：中文",
        f"- **时长**：{duration_str}",
        f"- **生成时间**：{dt.date.today().isoformat()}",
        "", "---", "",
    ]
    for seg in result_whisper["segments"]:
        text = seg["text"].strip()
        if text:
            lines.append(f"[{_fmt(seg['start'])} - {_fmt(seg['end'])}] {text}")
    
    md_path = out_dir / f"{_safe_filename(author_display)}_《{_safe_filename(title_display)}》_逐字稿.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    
    # Save metadata
    meta = {
        "title": title_display,
        "author": author_display,
        "platform": platform,
        "source": str(input_path),
        "source_url": source_url,
        "duration": duration_sec,
        "model": model_name,
        "segments": len(result_whisper["segments"]),
        "word_count": sum(len(s["text"]) for s in result_whisper["segments"]),
    }
    (out_dir / ".metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    
    record["status"] = "ok"
    record["files"] = [str(input_path), str(wav_path), str(md_path)]
    record["bytes"] = input_path.stat().st_size + wav_path.stat().st_size + md_path.stat().st_size
    record["note"] = f"时长{duration_str}, {meta['word_count']}字"
    return record
```

### Key Notes

- **Works with any format** that ffmpeg supports: mp4, mkv, avi, mov, wav, mp3, m4a, flac, aac, etc.
- **Metadata guessing**: If title/author are not provided, derive from filename or ask the user.
- **For long audio (>30 min)**: Use the chunking approach from Task 4 instead of direct transcribe.
- **Output follows standard format** — same `[MM:SS - MM:SS]` timestamps, same Chinese metadata fields.
- **The input file is NOT copied to Outputs** — only the generated WAV and transcript go there. The original file stays where it was.

---

## Task 5: Batch / Playlist Download

### Input Sources
- Direct list of URLs
- Text file with one URL per line (`--url-file`)
- `z-web-pack` media inventory (`--inventory`)

### Batch Workflow

```python
for index, url in enumerate(urls, start=1):
    if already_downloaded(unique_id(url)):
        records.append({"status": "skipped", "note": "already in archive"})
        continue
    try:
        record = process_one(url, out_dir)
        records.append(record)
        if record["status"] == "ok":
            mark_downloaded(unique_id(url))
    except Exception as e:
        records.append({"status": "failed", "url": url, "note": str(e)[:200]})
        time.sleep(3)
    time.sleep(2)  # Rate limiting

# Retry failures after first pass
failed = [r for r in records if r["status"] == "failed"]
for record in failed:
    pass  # retry logic
```

### Playlist Support

Default: **`--no-playlist`** (single video). For full playlist:

```bash
yt-dlp --yes-playlist --download-archive archive.txt \
  -f "bv*+ba/b" -o "{out_dir}/%(playlist_title)s/%(title)s.%(ext)s" \
  "PLAYLIST_URL"
```

---

## Final Quality Checks (MANDATORY)

Before reporting completion, ALWAYS verify:

```python
def verify_output(out_dir: Path, expect_video=True, expect_audio=True,
                  expect_transcript=True) -> list[str]:
    issues = []
    mp4s = list(out_dir.glob("*.mp4"))
    if expect_video and not mp4s:
        issues.append("No MP4 video found")
    elif mp4s:
        for mp4 in mp4s:
            if mp4.stat().st_size < 1024*1024:
                issues.append(f"Video too small: {mp4.name}")
    
    wavs = list(out_dir.glob("*.wav"))
    if expect_audio and not wavs:
        issues.append("No WAV audio found")
    
    transcripts = list(out_dir.glob("*逐字稿*"))
    if expect_transcript and not transcripts:
        issues.append("No transcript file found")
    
    if not (out_dir / "download-report.md").exists():
        issues.append("No download-report.md found")
    
    return issues
```

---

## GPU & Performance Notes

- **RTX 3080 (16GB VRAM):** One `large-v3-turbo` instance. 10-min segment ≈ 1 min.
- **NEVER run multiple Whisper instances** on same GPU — VRAM contention.
- **Typical throughput:** ~5-10 min wall-clock per video (download + convert + whisper).

---

## Windows Environment Critical Notes (MUST READ)

| Issue | Solution |
|-------|----------|
| **WSL popup on `import whisper`** | Set `os.environ["WHISPER_NO_WSL"] = "1"` BEFORE import |
| **Exit code 1 on Windows** | Ignore it. Check `Get-Process python | Select-Object Id, CPU` — if CPU is rising, it's working. |
| **Never use `python -c` for long tasks** | Always write to a `.py` file and execute |
| **`transcribe()` TypeError (WindowsPath)** | Pass `str(audio_path)`, never a Path object |
| **Chrome cookie database locked** | Close Chrome first, or use "Get cookies.txt" extension |
| **Foreground 600s hard limit** | Use `background=true` + `notify_on_complete=true` |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| WSL popup on `import whisper` | Set `WHISPER_NO_WSL=1` env var before import |
| Whisper outputs Traditional Chinese | Use `large-v3-turbo` for native Simplified output |
| Background process exit code 1 | Check CPU time via `Get-Process python`. Ignore exit code. |
| Whisper `transcribe()` TypeError | Pass `str(audio_path)`, not Path object |
| **Bilibili HTTP 412 (no cookies)** | Use direct playurl API for audio |
| **Douyin yt-dlp fails** | Use Playwright API interception |
| **Douyin returns HTML not JSON** | Use Playwright method |
| **X/Twitter "No video found"** | Could be image/text tweet. Fall back to image + text extraction. |
| **Zhihu API 403** | Use non-headless Playwright + stealth scripts |
| **Zhihu headless fails** | Set `headless=False` + `--disable-blink-features=AutomationControlled` |
| **Xiaohongshu** | Use yt-dlp (works great!) |
| **YouTube blocked** | Try Invidious fallback (360p) |
| Whisper hallucination | Split + `condition_on_previous_text False` + repetition detection |
| `--vad_filter True` extremely slow | Don't use. Use segment splitting instead. |
| Bilibili CDN 403 | Add `Referer: https://www.bilibili.com/` header |
| Playwright browser not found | `python -m playwright install chromium` |
| Whisper out of memory | Use smaller model or split into chunks |
| Timestamp offsets after chunking | Use `scripts/merge_chunks.py` |
| WeChat Channels parse fails | Retry once. Check if link has expired. |
| **WeChat Official Accounts (公众号)** | Direct `requests.get()` works. Images need `Referer: mp.weixin.qq.com` header. Images use `data-src` not `src` (lazy loading). |

---

## Additional Resources

- Platform-specific details: `references/platforms.md`
- Windows transcription scripts: `scripts/transcribe_windows.py`
- Merge/chunk utilities: `scripts/merge_chunks.py`
- Comment extraction: `scripts/extract_comments.py`
