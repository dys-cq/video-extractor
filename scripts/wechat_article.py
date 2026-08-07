"""
WeChat Official Accounts (微信公众号) article extractor — 3-tier fallback.

Tier 1: Direct HTTP request (fastest, works for most articles)
Tier 2: Playwright non-headless (bypasses basic verification)
Tier 3: Playwright with persistent user data dir (for heavily restricted articles,
        user logs in once, cookie is reused)

Usage:
    from scripts.wechat_article import extract
    result = extract("https://mp.weixin.qq.com/s/xxx", out_dir)
"""
import os, re, json, datetime as dt
from pathlib import Path
import requests

from .utils import (
    safe_filename, download_with_resume, html_to_markdown,
    build_article_md,
)

WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

IMG_HEADERS = dict(WX_HEADERS)
IMG_HEADERS["Referer"] = "https://mp.weixin.qq.com/"


def can_handle(url: str) -> bool:
    return "mp.weixin.qq.com/s/" in url


def _parse_metadata_from_html(html: str) -> dict:
    """Extract article metadata from HTML string."""
    info = {"title": "", "author": "", "publish_time": "", "content_html": "", "images": []}
    
    # Title - multiple fallbacks
    for pat in [
        r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>',
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            info["title"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if info["title"]:
                break
    
    # Author
    for pat in [
        r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
        r'var nickname = "([^"]+)"',
        r'<span[^>]*class="profile_nickname"[^>]*>(.*?)</span>',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            info["author"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if info["author"]:
                break
    
    # Publish time
    m = re.search(r'var ct = "(\d+)"', html)
    if m:
        try:
            info["publish_time"] = dt.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d")
        except:
            pass
    
    # Content
    for pat in [
        # Match js_content div, ending before the trailing UI markers
        r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*(?:<div id="js_tags_preview_toast"|<div id="content_bottom_area"|<div id="font_pannel_area"|</div>\s*</div>)',
        r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]*class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            info["content_html"] = m.group(1)
            break
    
    # Images (data-src = real URL for lazy loading)
    if info["content_html"]:
        for m in re.finditer(r'<img[^>]+data-src="([^"]+)"', info["content_html"]):
            u = m.group(1)
            if u.startswith('http') and 'mmbiz' in u and u not in info["images"]:
                info["images"].append(u)
        # Fallback to src
        if not info["images"]:
            for m in re.finditer(r'<img[^>]+src="([^"]+)"', info["content_html"]):
                u = m.group(1)
                if u.startswith('http') and 'mmbiz' in u and u not in info["images"]:
                    info["images"].append(u)
    
    return info


def _is_verification_page(html: str, body_text: str = "") -> bool:
    """Check if page is a verification/error page instead of article content."""
    text = body_text if body_text else html
    keywords = ["环境异常", "完成验证", "验证码", "访问受限", "被屏蔽"]
    return any(k in text for k in keywords)


def _download_images(image_urls: list, content_html: str, out_dir: Path) -> tuple:
    """Download images and replace URLs in content_html with local filenames."""
    downloaded = []
    for i, img_url in enumerate(image_urls, 1):
        try:
            ext = '.jpg'
            full_url = img_url
            if 'wx_fmt=png' in img_url:
                ext = '.png'
            elif 'wx_fmt=gif' in img_url:
                ext = '.gif'
            elif 'wx_fmt=' not in img_url:
                sep = '&' if '?' in img_url else '?'
                full_url = img_url + sep + 'wx_fmt=jpeg'
            
            target = out_dir / f"image_{i}{ext}"
            dl = download_with_resume(full_url, target, headers=IMG_HEADERS, max_mb=20)
            if dl["status"] == "ok" and dl["bytes"] > 2000:
                downloaded.append((i, target.name, dl["bytes"]))
                content_html = content_html.replace(img_url, target.name)
                if full_url != img_url:
                    content_html = content_html.replace(full_url, target.name)
        except Exception:
            continue
    return downloaded, content_html


def _clean_body_text(text: str) -> str:
    """Clean extracted body text: strip trailing hashtag lines and page meta."""
    # Strip HTML tags (some WeChat HTML slips through as raw tags, e.g. <hr>, <mp-style-type>)
    text = re.sub(r'<[^>]+>', '', text)
    # Normalize whitespace after tag stripping
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.split('\n')]
    
    # WeChat page-UI remnant phrases (not article content)
    UI_PHRASES = {
        '预览时标签不可点', '微信扫一扫', '关注该公众号', '知道了', '收录于',
        '喜欢作者', '发消息', '其它金额', '最低赞赏', '确定', '取消', '允许',
    }
    # Patterns for WeChat page-meta remnants (not part of article body)
    time_meta = re.compile(r'^(昨天|今天|前天|\d+分钟前|\d+小时前|\d{4}-\d{2}-\d{2})[\s,，]*\d{0,2}:?\d{0,2}$')
    keep = []
    for line in lines:
        stripped = line.strip()
        # Skip hashtag-only lines (WeChat auto tags at the end)
        if stripped.startswith('#') and stripped.count('#') > 1:
            continue
        # Skip WeChat UI remnant lines
        if stripped in UI_PHRASES:
            continue
        # Skip pure-meta lines (location/time remnants)
        if stripped in ('北京', '上海', '广州', '深圳', '微信', '原创') \
                or stripped.endswith('合集') and len(stripped) <= 12 \
                or re.fullmatch(r'[，,。\s]*', stripped) \
                or time_meta.match(stripped):
            continue
        keep.append(line)
    # Trim trailing blank lines only
    while keep and not keep[-1].strip():
        keep.pop()
    return '\n'.join(keep).strip()


def _save_output(info: dict, content_html: str, url: str, out_dir: Path,
                 method: str = "http") -> dict:
    """Save article content and metadata to output directory."""
    title = info.get("title", "")
    author = info.get("author", "")
    publish_time = info.get("publish_time", "")
    images = info.get("images", [])
    
    # Download images
    downloaded_images, content_html = _download_images(images, content_html, out_dir)
    
    # Convert to markdown
    if info.get("content_text"):  # clean text body (image-message articles)
        content_md = _clean_body_text(info["content_text"])
    else:
        content_md = _clean_body_text(html_to_markdown(content_html))
    
    # Save markdown
    title_safe = safe_filename(title[:60], "wechat-article")
    author_safe = safe_filename(author, "wechat")
    md_path = out_dir / f"{author_safe}_《{title_safe}》_公众号文章.md"
    
    full_md = build_article_md(
        title=title, author=author, url=url, platform="微信公众号",
        content_md=content_md, image_count=len(downloaded_images),
        publish_time=publish_time,
    )
    md_path.write_text(full_md, encoding="utf-8")
    
    all_files = [str(md_path)] + [str(out_dir / n) for _, n, _ in downloaded_images]
    total_bytes = sum(s for _, _, s in downloaded_images) + md_path.stat().st_size
    
    record = {
        "url": url, "kind": "wechat-article", "platform": "微信公众号",
        "status": "ok", "files": all_files, "bytes": total_bytes,
        "note": f"{len(content_md)}字, {len(downloaded_images)}图 ({method})",
    }
    
    # Metadata
    (out_dir / ".metadata.json").write_text(
        json.dumps({
            "title": title, "author": author, "url": url,
            "publish_time": publish_time, "platform": "微信公众号",
            "word_count": len(content_md), "image_count": len(downloaded_images),
            "method": method,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    
    return record


def _tier1_http(url: str, out_dir: Path) -> dict:
    """Tier 1: Direct HTTP request."""
    try:
        r = requests.get(url, headers=WX_HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        
        info = _parse_metadata_from_html(r.text)
        
        # Check if we got actual content
        if not info["content_html"] or len(info["content_html"]) < 500:
            return None
        if _is_verification_page(r.text):
            return None
        
        return _save_output(info, info["content_html"], url, out_dir, method="http")
    except Exception:
        return None


def _tier2_playwright(url: str, out_dir: Path) -> dict:
    """Tier 2: Playwright non-headless with stealth."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
            )
            context = browser.new_context(
                user_agent=WX_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # Scroll to trigger lazy loading
            page.evaluate("""async () => {
                for (let i = 0; i < document.body.scrollHeight; i += 300) {
                    window.scrollTo(0, i);
                    await new Promise(r => setTimeout(r, 100));
                }
                window.scrollTo(0, 0);
            }""")
            page.wait_for_timeout(1000)
            
            body_text = page.inner_text("body")
            
            # Check if content is there
            js_content = page.query_selector("#js_content")
            if not js_content:
                browser.close()
                return None
            
            if _is_verification_page("", body_text):
                browser.close()
                return None
            
            # Extract via JS eval (most reliable)
            info = page.evaluate("""() => {
                const r = {title: '', author: '', publish_time: '', content_html: '', images: []};
                
                // Title
                const titleEl = document.querySelector('#activity-name');
                if (titleEl) r.title = titleEl.innerText.trim();
                if (!r.title) {
                    const ogTitle = document.querySelector('meta[property="og:title"]');
                    if (ogTitle) r.title = ogTitle.content;
                }
                
                // Author - iterate all nickname-ish elements, take first non-empty
                const nickEls = document.querySelectorAll('[class*="nickname"], [id*="nickname"]');
                for (const el of nickEls) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 0 && text.length <= 20) {
                        r.author = text;
                        break;
                    }
                }
                
                // Publish time from JS var ct
                try { r.publish_time = new Date(ct * 1000).toISOString().slice(0, 10); } catch(e) {}
                
                // Content: prefer .share_notice (image-message articles have clean text body here)
                const shareNotice = document.querySelector('#js_image_content p.share_notice')
                    || document.querySelector('p.share_notice')
                    || document.querySelector('.share_notice');
                if (shareNotice) {
                    r.content_text = shareNotice.innerText.trim();
                }
                const content = document.querySelector('#js_content');
                if (content) r.content_html = content.innerHTML;
                
                // Images
                if (content) {
                    content.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('data-src') || img.getAttribute('src');
                        if (src && src.startsWith('http') && src.includes('mmbiz')) {
                            if (!r.images.includes(src)) r.images.push(src);
                        }
                    });
                }
                
                // Images in <ol> via background-image (image-message swiper articles)
                // WeChat puts body images as CSS background-image on li elements inside an ol
                document.querySelectorAll('ol li').forEach(li => {
                    const bg = window.getComputedStyle(li).backgroundImage;
                    if (bg && bg.includes('mmbiz')) {
                        const m = bg.match(/url\\("?([^")]+)"?\\)/);
                        if (m) {
                            let u = m[1].replace(/&amp;/g, '&');
                            // /300 thumbnail -> /0 original
                            u = u.replace(/\\/300\\?/, '/0?');
                            u = u.replace(/&from=appmsg&wxfrom=\\d+/g, '');
                            if (!r.images.includes(u)) r.images.push(u);
                        }
                    }
                });
                
                // Cover image from og:image (for image-message articles with no body images)
                if (!r.images.length) {
                    const ogImg = document.querySelector('meta[property="og:image"]');
                    if (ogImg && ogImg.content && ogImg.content.startsWith('http')) {
                        r.images.push(ogImg.content);
                    }
                }
                
                return r;
            }""")
            
            browser.close()
            
            if not info.get("content_html") or len(info["content_html"]) < 500:
                return None
            
            return _save_output(info, info["content_html"], url, out_dir, method="playwright")
    except Exception:
        return None


def _tier3_persistent(url: str, out_dir: Path, user_data_dir: Path = None) -> dict:
    """Tier 3: Playwright with persistent user data (user's Chrome profile).
    
    User needs to have Chrome set up with --remote-debugging-port=9222,
    or we can use a persistent context from a user data directory.
    For now, we try connecting to an already-running Chrome via CDP.
    """
    # Try CDP connection to running Chrome on port 9222
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    
    import socket as sock_mod
    sock = sock_mod.socket(sock_mod.AF_INET, sock_mod.SOCK_STREAM)
    sock.settimeout(1)
    port_open = (sock.connect_ex(('127.0.0.1', 9222)) == 0)
    sock.close()
    
    if not port_open:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            # Scroll for lazy images
            page.evaluate("""async () => {
                for (let i = 0; i < document.body.scrollHeight; i += 300) {
                    window.scrollTo(0, i);
                    await new Promise(r => setTimeout(r, 100));
                }
            }""")
            page.wait_for_timeout(1000)
            
            js_content = page.query_selector("#js_content")
            if not js_content:
                page.close()
                return None
            
            info = page.evaluate("""() => {
                const r = {title: '', author: '', publish_time: '', content_html: '', images: []};
                const titleEl = document.querySelector('#activity-name');
                if (titleEl) r.title = titleEl.innerText.trim();
                const nickEls = document.querySelectorAll('[class*="nickname"], [id*="nickname"]');
                for (const el of nickEls) {
                    const text = el.innerText?.trim();
                    if (text && text.length > 0 && text.length <= 20) {
                        r.author = text;
                        break;
                    }
                }
                try { r.publish_time = new Date(ct * 1000).toISOString().slice(0, 10); } catch(e) {}
                const shareNotice = document.querySelector('#js_image_content p.share_notice')
                    || document.querySelector('p.share_notice')
                    || document.querySelector('.share_notice');
                if (shareNotice) {
                    r.content_text = shareNotice.innerText.trim();
                }
                const content = document.querySelector('#js_content');
                if (content) {
                    r.content_html = content.innerHTML;
                    content.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('data-src') || img.getAttribute('src');
                        if (src && src.startsWith('http') && src.includes('mmbiz')) {
                            if (!r.images.includes(src)) r.images.push(src);
                        }
                    });
                }
                // Images in <ol> via background-image (image-message swiper articles)
                document.querySelectorAll('ol li').forEach(li => {
                    const bg = window.getComputedStyle(li).backgroundImage;
                    if (bg && bg.includes('mmbiz')) {
                        const m = bg.match(/url\\("?([^")]+)"?\\)/);
                        if (m) {
                            let u = m[1].replace(/&amp;/g, '&');
                            u = u.replace(/\\/300\\?/, '/0?');
                            u = u.replace(/&from=appmsg&wxfrom=\\d+/g, '');
                            if (!r.images.includes(u)) r.images.push(u);
                        }
                    }
                });
                if (!r.images.length) {
                    const ogImg = document.querySelector('meta[property="og:image"]');
                    if (ogImg && ogImg.content && ogImg.content.startsWith('http')) {
                        r.images.push(ogImg.content);
                    }
                }
                return r;
            }""")
            
            page.close()
            browser.close()  # Disconnect only
            
            if not info.get("content_html") or len(info["content_html"]) < 500:
                return None
            
            return _save_output(info, info["content_html"], url, out_dir, method="cdp")
    except Exception:
        return None


def extract(url: str, out_dir: Path, *, prefer_method: str = "auto") -> dict:
    """Extract a WeChat article with 3-tier fallback.
    
    Args:
        url: WeChat article URL (mp.weixin.qq.com/s/...)
        out_dir: Output directory
        prefer_method: "auto" (tries all tiers), "http", "playwright", "cdp"
    
    Returns:
        Record dict. Status is "failed" if all tiers fail.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    
    base_record = {
        "url": url, "kind": "wechat-article", "platform": "微信公众号",
        "status": "failed", "files": [], "bytes": 0, "note": "",
    }
    
    if prefer_method in ("auto", "http"):
        result = _tier1_http(url, out_dir)
        if result:
            return result
    
    if prefer_method in ("auto", "playwright"):
        result = _tier2_playwright(url, out_dir)
        if result:
            return result
    
    if prefer_method in ("auto", "cdp"):
        result = _tier3_persistent(url, out_dir)
        if result:
            return result
    
    base_record["note"] = "all methods failed (article may require login or verification)"
    return base_record
