# Platform-Specific Reference

## Douyin (抖音)

**URL patterns:**
- Short: `https://v.douyin.com/xxxxx/`
- Full: `https://www.douyin.com/video/{video_id}`

**Transcript:**
1. Resolve short URL: `curl -sL -o /dev/null -w "%{url_effective}" "SHORT_URL"`
2. Download audio: `yt-dlp -x --audio-format wav -o "/tmp/audio.%(ext)s" "URL"`
3. Transcribe with Whisper

**Comments — Playwright API interception:**

Douyin's comment API (`/aweme/v1/web/comment/list/`) requires browser-generated tokens (`X-Bogus`, `msToken`, etc.). Direct HTTP requests fail. Use Playwright to intercept responses:

```python
import asyncio
from playwright.async_api import async_playwright
import json

async def extract_douyin_comments(url, max_scrolls=15):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN'
        )
        page = await context.new_page()

        comments = []
        seen_ids = set()

        async def handle_response(response):
            if 'comment/list' in response.url and response.status == 200:
                try:
                    data = await response.json()
                    for c in data.get('comments', []):
                        cid = c.get('cid', '')
                        if cid not in seen_ids:
                            seen_ids.add(cid)
                            comments.append({
                                'user': c.get('user', {}).get('nickname', ''),
                                'text': c.get('text', ''),
                                'likes': c.get('digg_count', 0),
                                'replies': c.get('reply_comment_total', 0),
                                'reply_list': [{
                                    'user': r.get('user', {}).get('nickname', ''),
                                    'text': r.get('text', ''),
                                    'likes': r.get('digg_count', 0)
                                } for r in (c.get('reply_comment', []) or [])]
                            })
                except:
                    pass

        page.on('response', handle_response)

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        except:
            pass

        await asyncio.sleep(8)  # Wait for initial load

        for i in range(max_scrolls):
            await page.evaluate('window.scrollBy(0, 800)')
            await asyncio.sleep(1.5)

        await browser.close()
        return sorted(comments, key=lambda x: x['likes'], reverse=True)
```

**Key notes:**
- `wait_until='networkidle'` often times out on Douyin; use `'domcontentloaded'` instead
- Scroll triggers lazy-loading of additional comments
- Each scroll batch loads ~5-10 comments
- Typical yield: 10-50 comments depending on scroll depth

---

## Bilibili (B站)

**URL patterns:**
- `https://www.bilibili.com/video/BVxxxxxx`
- `https://b23.tv/xxxxx` (short link)
- `https://space.bilibili.com/xxxxx` (user space — find BV号 from their video list)

### Transcript Extraction

**WARNING: yt-dlp often fails with HTTP 412 on Bilibili** (Precondition Failed). This is because Bilibili requires cookies/authentication that yt-dlp doesn't provide. Use the direct API approach below instead.

#### Method: Playwright API interception (PRIMARY)

Douyin yt-dlp support is unreliable — it almost always returns
"Fresh cookies are needed" and fails. **Go straight to Playwright**,
don't waste time trying yt-dlp first.

**Step 1: Get video metadata and CID list**

For multi-part videos (合集/collections), each part has its own CID. Use the view API:

```python
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.bilibili.com/'
}

def get_video_info(bvid):
    """Get video title and all part CIDs from view API."""
    resp = requests.get(
        f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
        headers=HEADERS
    ).json()
    data = resp['data']
    title = data['title']
    pages = []
    for p in data['pages']:
        pages.append({
            'page': p['page'],        # Part number (1-indexed)
            'cid': p['cid'],           # Content ID for this part
            'title': p['part'],        # Part title
            'duration': p['duration']  # Duration in seconds
        })
    return title, pages
```

**Step 2: Get DASH audio URL via playurl API**

```python
def get_audio_url(bvid, cid):
    """
    Get DASH audio stream URL.
    fnval=16 requests DASH format (separate video + audio streams).
    """
    resp = requests.get(
        f'https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&fnver=0&fourk=1',
        headers=HEADERS
    ).json()
    audio_streams = resp['data']['dash']['audio']
    # Pick highest quality audio stream
    best = sorted(audio_streams, key=lambda x: x['bandwidth'], reverse=True)[0]
    return best['baseUrl']
```

**Step 3: Download m4s audio (Referer header is CRITICAL)**

```python
def download_audio(audio_url, output_path):
    """
    Download DASH audio (m4s format).
    CRITICAL: Must include Referer header, otherwise CDN returns 403.
    """
    resp = requests.get(audio_url, headers=HEADERS, stream=True)
    resp.raise_for_status()
    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
```

**Step 4: Convert m4s to WAV for Whisper**

```python
import subprocess

def convert_to_wav(input_path, output_path):
    """Convert m4s audio to 16kHz mono WAV (Whisper's preferred format)."""
    subprocess.run([
        'ffmpeg', '-y', '-i', input_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        output_path
    ], check=True, capture_output=True)
```

**Step 5: Transcribe with Whisper** (use anti-hallucination pipeline from SKILL.md)

#### Complete pipeline for a single video part:

```python
def process_video_part(bvid, cid, page_num, title, output_dir):
    """Full pipeline: get audio URL → download → convert → transcribe."""
    import os, shutil

    audio_dir = os.path.join(output_dir, 'audio_files', f'P{page_num:03d}')
    os.makedirs(audio_dir, exist_ok=True)

    # 1. Get audio URL
    audio_url = get_audio_url(bvid, cid)

    # 2. Download m4s
    m4s_path = os.path.join(audio_dir, 'audio.m4s')
    download_audio(audio_url, m4s_path)

    # 3. Convert to WAV
    wav_path = os.path.join(audio_dir, 'audio.wav')
    convert_to_wav(m4s_path, wav_path)

    # 4. Transcribe (with anti-hallucination for long videos)
    transcript = transcribe_long_audio(wav_path, os.path.join(output_dir, 'transcripts'))

    # 5. Save transcript
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
    txt_path = os.path.join(output_dir, 'transcripts', f'P{page_num:03d}_{safe_title}.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(transcript)

    # 6. Cleanup audio files
    shutil.rmtree(audio_dir, ignore_errors=True)

    return transcript
```

### Multi-part Video (合集) Handling

Bilibili collections/courses often have 50-100+ parts under a single BV号. The view API returns all parts with their CIDs.

**Key considerations:**
- Always fetch the full CID list first via `/x/web-interface/view?bvid=xxx`
- Process parts sequentially (one at a time) to avoid overwhelming GPU/network
- Use progress.json for resume support (see SKILL.md batch processing section)
- Add 2-3 second delays between parts for rate limiting
- Network errors (DNS, connection reset) are common — record failures and retry

**Finding BV号 from a user space:**
1. Visit `https://space.bilibili.com/{uid}/video` to find the BV号
2. Or search: `https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=xxx`

### Comments

Method 1 — Direct API (BV号 required):
```python
import requests

def get_bilibili_comments(bvid):
    """Get comments for a Bilibili video by BV ID."""
    # First get aid (avid)
    info = requests.get(
        f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
        headers={'User-Agent': 'Mozilla/5.0'}
    ).json()
    aid = info['data']['aid']

    # Get comments (page 1, sort by likes)
    comments = requests.get(
        f'https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&sort=1',
        headers={'User-Agent': 'Mozilla/5.0'}
    ).json()

    result = []
    for c in comments.get('data', {}).get('replies', []) or []:
        result.append({
            'user': c['member']['uname'],
            'text': c['content']['message'],
            'likes': c['like'],
            'replies': c['rcount']
        })
    return result
```

Method 2 — yt-dlp (may work for some videos, but often fails with 412):
```bash
yt-dlp --write-comments --skip-download --print-json "BILIBILI_URL"
```

**Key notes:**
- Bilibili API is more accessible than Douyin's — no complex signature required for basic queries
- For full comment threads, paginate with `pn` parameter
- Some videos may require login cookie for comments
- DASH audio format returns m4s files (not directly playable) — must convert via ffmpeg
- The `Referer: https://www.bilibili.com/` header is MANDATORY for all CDN downloads

---

## YouTube

**URL patterns:**
- `https://www.youtube.com/watch?v=xxxxx`
- `https://youtu.be/xxxxx`

**Transcript:**
```bash
# Method 1: Auto-generated subtitles (fastest)
yt-dlp --write-auto-subs --sub-langs "zh-Hans,zh,en" --sub-format vtt --skip-download -o "/tmp/subs" "URL"

# Method 2: Whisper fallback (if no subtitles available)
yt-dlp -x --audio-format wav -o "/tmp/audio.%(ext)s" "URL"
whisper /tmp/audio.wav --language auto --model large-v3-turbo --output_dir /tmp/
```

**Comments:**
```bash
# yt-dlp supports YouTube comments natively
yt-dlp --write-comments --skip-download --print-json "URL" 2>/dev/null | \
  python -c "
import sys, json
data = json.load(sys.stdin)
for c in data.get('comments', []):
    print(f\"[{c.get('author','?')}] ({c.get('like_count',0)} likes): {c.get('text','')}\")
"
```

**Key notes:**
- YouTube has the best yt-dlp support; most operations work without workarounds
- Auto-subtitles are often available and faster than Whisper
- Comment extraction may be slow for videos with thousands of comments

---

## X / Twitter

**URL patterns:**
- `https://x.com/{user}/status/{tweet_id}`
- `https://twitter.com/{user}/status/{tweet_id}`

### Tweet Types

| Type | Detection | Extraction |
|------|-----------|------------|
| **Video** | yt-dlp finds video, or `video.twimg.com` in XHR | Download MP4 → extract audio → Whisper transcribe |
| **Image/GIF** | `pbs.twimg.com/media/` in image URLs | Download images (orig quality) → optional OCR |
| **Text-only** | No media found | Save tweet text as Markdown |

### Workflow Decision Tree

```
Given X/Twitter URL
   |
   v
Try yt-dlp → finds video? → YES → Video download + transcribe + report
   |
   NO
   |
   v
Playwright visit page → find video URL? → YES → Download + transcribe + report
   |
   NO
   |
   v
Find images (pbs.twimg.com/media/)? → YES → Download images + save tweet MD + report
   |
   NO
   |
   v
Text-only tweet → Save tweet text as MD + report
```

**IMPORTANT: Always produce output, never fail silently.** Even if there's no video,
save what you can (text, images) and include it in the download-report.

### Video Tweets

**Method: Playwright (primary)**

X/Twitter yt-dlp is unreliable — often fails with "No video could be found"
or requires login cookies. **Use Playwright as the primary method** for
both video and image/text tweets.

For video tweets specifically, yt-dlp MIGHT work if you have a logged-in
browser cookie file, but Playwright is more consistent.
```python
from playwright.sync_api import sync_playwright

def extract_twitter_video(url: str) -> dict:
    """Extract video URL from X/Twitter using Playwright."""
    video_url = None
    tweet_text = ""
    
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
        
        try:
            page.goto(url, timeout=30000)
            page.wait_for_timeout(5000)
        except Exception:
            pass  # Timeout is OK if we already got data
        
        # Get tweet text from article element
        article = page.query_selector("article")
        if article:
            tweet_text = article.inner_text()
        
        browser.close()
    
    return {"video_url": video_url, "tweet_text": tweet_text}
```

### Image / Text-Only Tweets

```python
import requests
import re
from pathlib import Path

def extract_twitter_images(page, out_dir: Path) -> list[str]:
    """
    Extract all images from a tweet page and download them at original quality.
    Returns list of downloaded file paths.
    """
    downloaded = []
    image_urls = set()
    
    # Method 1: img elements with pbs.twimg.com/media/ src
    images = page.query_selector_all("img")
    for img in images:
        src = img.get_attribute("src") or ""
        if "pbs.twimg.com/media/" in src:
            base = src.split('?')[0]
            image_urls.add(base + "?format=jpg&name=orig")
    
    # Method 2: background-image in tweetPhoto divs
    media_divs = page.query_selector_all("[data-testid='tweetPhoto']")
    for div in media_divs:
        style = div.evaluate("el => getComputedStyle(el).backgroundImage")
        if style and 'url(' in style:
            m = re.search(r'url\(["\']?(.+?)["\']?\)', style)
            if m:
                bg_url = m.group(1)
                if "pbs.twimg.com/media/" in bg_url:
                    base = bg_url.split('?')[0]
                    image_urls.add(base + "?format=jpg&name=orig")
    
    # Download each
    for i, img_url in enumerate(sorted(image_urls), 1):
        target = out_dir / f"image_{i}.jpg"
        try:
            r = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                target.write_bytes(r.content)
                downloaded.append(str(target))
        except Exception:
            continue
    
    return downloaded

def save_tweet_markdown(out_dir: Path, tweet_text: str, url: str,
                         author: str, images: list = None) -> Path:
    """Save tweet content as a formatted markdown file."""
    import datetime as dt
    image_count = len(images) if images else 0
    
    md_path = out_dir / f"{author}_tweet_content.md"
    content = f"""# Tweet Content

## Metadata
- **Author**: @{author}
- **Source**: <{url}>
- **Platform**: X / Twitter
- **Images**: {image_count}
- **Extracted**: {dt.datetime.now().isoformat(timespec='seconds')}

---

## Tweet Text

{tweet_text}

---

## Images

"""
    
    for i, img in enumerate(images or [], 1):
        fname = Path(img).name
        content += f"### Image {i}\n\n![image_{i}]({fname})\n\n"
    
    md_path.write_text(content, encoding="utf-8")
    return md_path
```

### Full Pipeline Script

```python
def process_twitter_url(url: str, out_dir: Path, ffmpeg: str = "ffmpeg") -> dict:
    """
    Full pipeline for any X/Twitter URL.
    Auto-detects tweet type and extracts accordingly.
    Returns a record dict for download-report.
    """
    import yt_dlp
    from playwright.sync_api import sync_playwright
    
    record = {
        "url": url,
        "kind": "x-twitter",
        "platform": "X/Twitter",
        "status": "failed",
        "files": [],
        "bytes": 0,
        "note": "",
    }
    
    # Step 1: Try yt-dlp (fastest for video)
    video_file = None
    try:
        ydl_opts = {"format": "bv*+ba/b", "outtmpl": str(out_dir / "%(title).60s.%(ext)s")}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # ... find downloaded file ...
            record["status"] = "ok"
            record["note"] = "video (yt-dlp)"
            # ... transcribe ...
            return record
    except Exception:
        pass  # Fall through to Playwright
    
    # Step 2: Playwright - detect type and extract
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 720},
        )
        
        # ... intercept video URLs, extract text, find images ...
        # See individual functions above
        
        browser.close()
    
    return record
```

### OCR for Image Tweets (Optional)

Only do OCR if user explicitly asks for it — it's slow and may not be needed.

```bash
pip install easyocr
```

```python
import easyocr
reader = easyocr.Reader(['ch_sim', 'en'])
result = reader.readtext('image_1.jpg')
# result is list of [bbox, text, confidence]
```

### Key Notes

- **X has strong anti-bot**: yt-dlp may fail without cookies. Playwright is more reliable.
- **Tweet detection is important**: Not all tweets have video. Always check first.
- **Never fail silently**: Even if it's just text + images, produce output and a report.
- **Image quality**: Use `?format=jpg&name=orig` for original resolution.
- **Multiple images**: A tweet can have up to 4 images. Check all of them.
- **GIFs**: Animated GIFs on X are often served as MP4 — may show up as video URLs.
- **Login**: For protected tweets or age-restricted content, you'll need browser cookies.

---

## Zhihu (知乎)

**URL patterns:**
- Answer: `https://www.zhihu.com/question/{qid}/answer/{aid}`
- Question: `https://www.zhihu.com/question/{qid}`
- Article/专栏: `https://zhuanlan.zhihu.com/p/{id}`

### Anti-Detection Notes

Zhihu has strong anti-bot protection:
- **Direct API (`api/v4/answers/{id}`)** → usually returns HTTP 403 without proper cookies
- **Headless Playwright** → often detected and returns empty content
- **Non-headless Playwright with stealth scripts** → works most of the time

### Method: Playwright (Non-headless + Stealth)

```python
from playwright.sync_api import sync_playwright

def extract_zhihu_answer(url: str) -> dict:
    """Extract text and images from a Zhihu answer.
    
    Returns dict with: question_title, author, content_text, content_html,
                       image_urls, upvotes, comments
    """
    result = {
        "question_title": "",
        "author": "",
        "content_text": "",
        "content_html": "",
        "image_urls": [],
        "upvotes": 0,
        "comments": 0,
    }
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # Non-headless is critical for bypassing detection
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        
        # Stealth scripts to avoid detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            window.chrome = {runtime: {}};
        """)
        
        page = context.new_page()
        
        # Visit homepage first to get basic cookies
        try:
            page.goto("https://www.zhihu.com/", timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
        except:
            pass
        
        # Visit the answer page
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  # Wait for content to render
        except Exception:
            pass  # Timeout is OK as long as content loaded
        
        # Extract content
        content_selectors = [
            ".RichContent-inner",
            "[class*='RichText']",
            ".Post-RichText",
            "article",
        ]
        
        for sel in content_selectors:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text()
                if len(text) > 100:
                    result["content_text"] = text
                    result["content_html"] = el.inner_html()
                    break
        
        # Question title
        for sel in ["h1.QuestionHeader-title", "[class*='QuestionHeader-title']", "h1"]:
            el = page.query_selector(sel)
            if el and el.inner_text().strip():
                result["question_title"] = el.inner_text().strip()
                break
        
        # Author
        for sel in [".AuthorInfo-name a", "[class*='AuthorInfo']", ".UserLink-link"]:
            el = page.query_selector(sel)
            if el:
                name = el.inner_text().strip().split('\n')[0].strip()
                if name:
                    result["author"] = name
                    break
        
        # Upvotes
        vote_el = page.query_selector(".VoteButton--up")
        if vote_el:
            result["upvotes"] = vote_el.inner_text().strip()
        
        # Extract image URLs from content
        if result["content_html"]:
            import re
            img_matches = re.findall(
                r'<img[^>]+(?:data-original|data-src|src)="([^"]+)"',
                result["content_html"]
            )
            seen = set()
            for src in img_matches:
                if src and src.startswith("http") and "zhimg" in src:
                    # Get high quality raw version
                    base = src.split('?')[0]
                    for suffix in ['_b.', '_s.', '_xl.', '_hd.']:
                        if suffix in base:
                            base = base.replace(suffix, '_r.')
                            break
                    if not base.endswith(('.jpg', '.png', '.gif')):
                        base += '.jpg'
                    if base not in seen:
                        seen.add(base)
                        result["image_urls"].append(base)
        
        browser.close()
    
    return result
```

### Image Download

```python
import requests

def download_zhihu_images(image_urls: list[str], out_dir: Path) -> list[str]:
    """Download Zhihu images at original quality.
    Returns list of downloaded file paths.
    """
    downloaded = []
    for i, url in enumerate(image_urls, 1):
        target = out_dir / f"image_{i}.jpg"
        try:
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.zhihu.com/",
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
        except Exception:
            continue
    return downloaded
```

### Markdown Output Format

```markdown
# {question_title}

## Metadata
- **Author**: {author}
- **Source**: <{url}>
- **Platform**: Zhihu
- **Upvotes**: {upvotes}
- **Comments**: {comments}
- **Images**: {image_count}
- **Extracted**: {datetime}

---

## Answer

{content_text}

---

## Images

### Image 1

![image_1](image_1.jpg)

...
```

### Supported Content Types

| Type | URL Pattern | Method |
|------|-------------|--------|
| Answer | `question/{qid}/answer/{aid}` | Playwright, `.RichContent-inner` |
| Article | `zhuanlan.zhihu.com/p/{id}` | Playwright, `.Post-RichText` |
| Question page | `question/{qid}` | Extract top answer + question description |

### Key Notes

- **Non-headless mode required**: Headless Playwright is easily detected by Zhihu
- **Stealth scripts needed**: Hide `navigator.webdriver`, fake plugins/languages
- **Warm up cookies first**: Visit zhihu.com homepage before the target URL
- **Image quality**: Always use `_r.jpg` (raw/original) suffix, not `_s.jpg` (small) or `_b.jpg` (big)
- **Referer header**: Required for image CDN downloads, or you get 403
- **API is faster but blocked**: `api/v4/answers/{id}` would be faster but returns 403 without login cookies
- **Login cookies**: For private content or higher rate limits, load Chrome cookies with `context.add_cookies()`

---

## WeChat Official Accounts (微信公众号 / mp.weixin.qq.com)

**URL pattern:** `https://mp.weixin.qq.com/s/{id}`

### Method: Direct HTTP request (PRIMARY)

Public articles are fully accessible without login. A simple `requests.get()`
returns the complete HTML with full article content.

**Difficulty: Easiest of all platforms.** — No anti-bot, no login needed.

### Extraction Code

```python
import requests, re, datetime as dt
from pathlib import Path

WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def extract_wechat_article(url: str, out_dir: Path) -> dict:
    # Fetch
    r = requests.get(url, headers=WX_HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text
    
    # Title
    title = ""
    m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html, re.DOTALL)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    
    # Author (公众号名称)
    author = ""
    for pat in [
        r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
        r'var nickname = "([^"]+)"',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            author = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            break
    
    # Publish time (from JS variable ct = unix timestamp)
    publish_time = ""
    m = re.search(r'var ct = "(\d+)"', html)
    if m:
        publish_time = dt.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d")
    
    # Content div
    content_html = ""
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    if m:
        content_html = m.group(1)
    
    # Images — WeChat uses data-src for lazy loading, NOT src
    image_urls = []
    for m in re.finditer(r'<img[^>]+data-src="([^"]+)"', content_html):
        u = m.group(1)
        if u.startswith('http') and 'mmbiz' in u and u not in image_urls:
            image_urls.append(u)
    
    # Download images (needs Referer header)
    img_headers = dict(WX_HEADERS)
    img_headers["Referer"] = "https://mp.weixin.qq.com/"
    
    downloaded = []
    for i, img_url in enumerate(image_urls, 1):
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
                downloaded.append((i, target.name, size))
                content_html = content_html.replace(img_url, target.name)
    
    # HTML → Markdown
    content_md = html_to_markdown(content_html)
    
    # Save with standard naming: {author}_《{title}》_公众号文章.md
    md_path = out_dir / f"{_safe_filename(author)}_《{_safe_filename(title[:60])}》_公众号文章.md"
    md_path.write_text(build_article_md(title, author, url, content_md, len(downloaded), publish_time),
                       encoding="utf-8")
    
    return {
        "status": "ok",
        "title": title,
        "author": author,
        "word_count": len(content_md),
        "image_count": len(downloaded),
        "files": [str(md_path)] + [str(out_dir / n) for _, n, _ in downloaded],
    }
```

### Key Notes

1. **No login required** — public articles return full content in HTML
2. **Images use `data-src` not `src`** — WeChat lazy-loads images, the real URL is in `data-src`
3. **Image downloads need `Referer: https://mp.weixin.qq.com/`** — the CDN checks it
4. **Append `wx_fmt=jpeg`** — ensures JPEG format (WeChat may serve webp otherwise)
5. **Content selector: `#js_content`** — always in the main article content div
6. **Author selector: `#js_name`** — the official account name
7. **Publish time: `var ct = "timestamp"`** — Unix timestamp in JS variable

---

## XiaoHongShu (小红书)

**URL patterns:**
- Short link: `http://xhslink.cn/o/xxxx` (redirects to full URL)
- Full: `https://www.xiaohongshu.com/explore/{note_id}`
- Discovery: `https://www.xiaohongshu.com/discovery/item/{note_id}`

### ⚡ IMPORTANT: yt-dlp Works Great for Xiaohongshu!

Unlike Douyin, X/Twitter, and Zhihu — **yt-dlp has excellent Xiaohongshu support**.
It can download both video and image-text notes (image-text notes are
converted to video slideshows). Downloads at full speed (~8 MB/s tested).

### Primary Method: yt-dlp

```python
import yt_dlp

def download_xhs(url: str, out_dir: Path) -> dict:
    """Download Xiaohongshu content via yt-dlp.
    Works for BOTH video and image-text notes.
    Returns info dict with title, file path, etc.
    """
    ydl_opts = {
        "outtmpl": str(out_dir / "%(title).60s.%(ext)s"),
        "format": "best",
        "quiet": False,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)
        # Actual file may have different extension
        base = Path(filepath).stem
        matches = list(out_dir.glob(f"{base}*"))
        for m in matches:
            if m.suffix.lower() in (".mp4", ".mkv", ".webm"):
                filepath = str(m)
                break
        
        return {
            "title": info.get("title", ""),
            "uploader": info.get("uploader", ""),
            "duration": info.get("duration", 0),
            "filepath": filepath,
            "filesize": Path(filepath).stat().st_size if Path(filepath).exists() else 0,
        }
```

### Getting Text Metadata (Title, Description, Author)

yt-dlp may not capture all text metadata for image-text notes.
Use Playwright to get the full text description and author info:

```python
from playwright.sync_api import sync_playwright

def extract_xhs_metadata(url: str) -> dict:
    """Get text metadata from Xiaohongshu note page."""
    result = {"title": "", "description": "", "author": "", "images": []}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0",
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Title
        title_el = page.query_selector("#detail-title") or page.query_selector(".note-title")
        if title_el:
            result["title"] = title_el.inner_text().strip()
        
        # Description
        desc_el = page.query_selector("#detail-desc") or page.query_selector(".note-desc")
        if desc_el:
            result["description"] = desc_el.inner_text().strip()
        
        # Author
        author_el = page.query_selector(".author-name") or page.query_selector(".user-name")
        if author_el:
            result["author"] = author_el.inner_text().strip().split('\n')[0]
        
        browser.close()
    
    return result
```

### Content Types

| Type | yt-dlp behavior | Playwright needed? |
|------|----------------|-------------------|
| **Video note** | Downloads video MP4 directly | Optional (for extra metadata) |
| **Image-text note** | Downloads as MP4 slideshow | Yes — to get the actual text and images |
| **Pure text note** | May not download anything | Yes — to get the text content |

### Key Notes

- **yt-dlp is the primary tool** for Xiaohongshu — it's fast and reliable
- Image-text notes are downloaded as video slideshows by yt-dlp
- Use **Playwright as complementary** tool for text metadata extraction
- Short links (xhslink.cn) redirect automatically — yt-dlp handles them fine
- This is a pleasant surprise compared to Douyin/Zhihu/X which all block yt-dlp

---

## General Tips

### Platform Method Priority Matrix

| Platform | Primary Method | Fallback | Notes |
|----------|---------------|----------|-------|
| **YouTube** | yt-dlp | Invidious proxy (360p) | yt-dlp works great for YouTube |
| **Bilibili** | Direct playurl API | yt-dlp (with cookies) | yt-dlp usually 412; API works without cookies |
| **WeChat Channels** | Online parser (`sph.litao.workers.dev`) | None known | Third-party service, no login needed |
| **Douyin** | Playwright API interception | yt-dlp + login cookies | yt-dlp almost always fails without cookies |
| **X/Twitter** | Playwright | yt-dlp + login cookies | yt-dlp unreliable; needs login for most content |
| **Zhihu** | Playwright (non-headless + stealth) | Direct API (rarely works) | yt-dlp returns 403; API also 403 without cookies |
| **Xiaohongshu** | yt-dlp (works well!) | Playwright (for text metadata) | Surprisingly good yt-dlp support — downloads 1080p video at full speed |
| **Xiaoyuzhou** | Direct HTTP download | None | Podcast audio is publicly accessible |

### Additional Tips

1. **yt-dlp is NOT "always first"** — see the matrix above. For platforms
   with strong anti-bot (Douyin, X, Zhihu, Xiaohongshu), go straight to
   Playwright.
2. **Bilibili is an exception** — yt-dlp usually returns HTTP 412. Use the
   direct playurl API instead (works without cookies for audio).
3. **Playwright is the workhorse for anti-bot platforms**, not a "last resort".
4. **Whisper model choice matters hugely for Chinese**:
   - `base`: ~5 min, poor Chinese — only for English content or quick preview
   - `small`: ~8 min, decent Chinese — good balance
   - `large-v3-turbo`: ~12 min, best Chinese — recommended for production
5. **Encoding**: Always set `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` for Chinese content
6. **Short URLs**: Resolve with `curl -sL -o /dev/null -w "%{url_effective}"` before processing
7. **Rate limiting**: Add 2-3 second delays between requests to avoid being blocked
8. **Anti-hallucination is critical for long videos**: Use `--condition_on_previous_text False`, split into 10-min segments, and detect hallucinated segments via line repetition analysis
9. **Never run multiple Whisper instances on the same GPU** — they compete for VRAM and everything slows down
10. **Do NOT use `--vad_filter True`** — it causes extreme slowdowns with minimal transcription benefit
11. **Network errors are transient**: Record failed videos and retry after the batch completes. DNS failures and connection resets are common on long-running batches
12. **Bilibili Referer header is mandatory**: All CDN downloads require `Referer: https://www.bilibili.com/` or they return 403
