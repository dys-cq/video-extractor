---
name: video-extractor
description: "Extract video transcripts, articles, comments, and text/image content from platforms including Douyin, Bilibili, YouTube, XiaoHongShu, WeChat Channels (微信视频号), WeChat Official Accounts (微信公众号), X/Twitter, Zhihu (知乎), and Xiaoyuzhou podcasts. Handles video, image-text, article, and text-only posts. Uses Whisper large-v3-turbo for native Simplified Chinese output. Supports batch downloads, resume, progress reports, and YouTube Invidious fallback. Triggers: \"提取文案\", \"提取评论\", \"视频转录\", \"video transcript\", \"extract comments\", \"video analysis\", \"播客转录\", \"小宇宙\", \"xiaoyuzhou\", \"下载视频\", \"video download\", \"提取推文\", \"twitter\", \"知乎\", \"zhihu\", \"公众号\", \"wechat\"."
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

### Method: Direct HTTP Request (PRIMARY)

WeChat public articles can be fetched directly with a simple GET request — no login needed, no Playwright required. The full article content is returned in the HTML.

### Workflow

```python
import requests, re, datetime as dt
from pathlib import Path

WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def extract_wechat_article(url: str, out_dir: Path) -> dict:
    record = {"url": url, "kind": "wechat-article", "platform": "微信公众号",
              "status": "failed", "files": [], "bytes": 0, "note": ""}
    
    # Step 1: Fetch page
    r = requests.get(url, headers=WX_HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    
    # Step 2: Extract metadata
    title = ""
    m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html, re.DOTALL)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    
    # Author (multiple fallbacks)
    author = ""
    for pat in [
        r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
        r'var nickname = "([^"]+)"',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            author = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            break
    
    # Publish time
    publish_time = ""
    m = re.search(r'var ct = "(\d+)"', html)
    if m:
        publish_time = dt.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d")
    
    # Step 3: Extract content
    content_html = ""
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    if m:
        content_html = m.group(1)
    
    # Step 4: Extract images (use data-src for lazy-loaded images)
    image_urls = []
    for m in re.finditer(r'<img[^>]+data-src="([^"]+)"', content_html):
        u = m.group(1)
        if u.startswith('http') and 'mmbiz' in u and u not in image_urls:
            image_urls.append(u)
    
    # Step 5: Download images with Referer
    downloaded_images = []
    img_headers = dict(WX_HEADERS)
    img_headers["Referer"] = "https://mp.weixin.qq.com/"
    
    for i, img_url in enumerate(image_urls, 1):
        try:
            # Add wx_fmt=jpeg for consistent format
            full_url = img_url + ('&wx_fmt=jpeg' if '?' in img_url else '?wx_fmt=jpeg')
            target = out_dir / f"image_{i}.jpg"
            r_img = requests.get(full_url, headers=img_headers, timeout=30, stream=True)
            if r_img.status_code == 200:
                size = 0
                with open(target, 'wb') as f:
                    for chunk in r_img.iter_content(64*1024):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size > 2000:
                    downloaded_images.append((i, target.name, size))
                    # Replace URL in content for local reference
                    content_html = content_html.replace(img_url, target.name)
        except:
            continue
    
    # Step 6: HTML → Markdown (see full html_to_markdown function in Task 2b)
    content_md = html_to_markdown(content_html)
    
    # Step 7: Save output (standard format)
    title_safe = _safe_filename(title[:60], "wechat-article")
    author_safe = _safe_filename(author, "wechat")
    md_path = out_dir / f"{author_safe}_《{title_safe}》_公众号文章.md"
    
    full_md = f"""# {title}

## 元数据
- **标题**：{title}
- **作者**：{author}
- **来源**：<{url}>
- **平台**：微信公众号
- **发布时间**：{publish_time}
- **图片数**：{len(downloaded_images)}
- **生成时间**：{dt.date.today().isoformat()}

---

## 正文

{content_md}
"""
    md_path.write_text(full_md, encoding="utf-8")
    
    record["status"] = "ok"
    record["files"] = [str(md_path)] + [str(out_dir / n) for _, n, _ in downloaded_images]
    record["bytes"] = sum(s for _, _, s in downloaded_images) + md_path.stat().st_size
    record["note"] = f"{len(content_md)}字, {len(downloaded_images)}图"
    
    (out_dir / ".metadata.json").write_text(
        json.dumps({"title": title, "author": author, "url": url,
                    "publish_time": publish_time, "platform": "微信公众号",
                    "word_count": len(content_md), "image_count": len(downloaded_images)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return record
```

### Key Notes

- **No login required** for public articles — direct GET works
- **Image URLs are in `data-src`** not `src` — WeChat uses lazy loading
- **Add `wx_fmt=jpeg`** to URL to ensure JPEG format (WeChat uses webp by default sometimes)
- **Include `Referer: https://mp.weixin.qq.com/`** when downloading images
- **Output filename pattern:** `{author}_《{title}》_公众号文章.md`

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
