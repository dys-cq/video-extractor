"""
WeChat Official Accounts (微信公众号) article extractor.

Usage:
    from scripts.wechat_article import extract
    result = extract("https://mp.weixin.qq.com/s/xxx", out_dir)
"""
import re, json, datetime as dt
from pathlib import Path
import requests

from .utils import (
    safe_filename, download_with_resume, html_to_markdown,
    build_article_md, write_reports,
)

WX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

IMG_HEADERS = dict(WX_HEADERS)
IMG_HEADERS["Referer"] = "https://mp.weixin.qq.com/"


def can_handle(url: str) -> bool:
    """Check if URL is a WeChat article."""
    return "mp.weixin.qq.com/s/" in url


def extract(url: str, out_dir: Path) -> dict:
    """Extract a WeChat official account article.

    Returns a record dict with status, files, bytes, etc.
    """
    record = {
        "url": url,
        "kind": "wechat-article",
        "platform": "微信公众号",
        "status": "failed",
        "files": [],
        "bytes": 0,
        "note": "",
    }

    # Fetch page
    r = requests.get(url, headers=WX_HEADERS, timeout=30)
    r.raise_for_status()
    html = r.text

    # Title
    title = ""
    m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html, re.DOTALL)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # Author
    author = ""
    for pat in [
        r'<a[^>]*id="js_name"[^>]*>(.*?)</a>',
        r'var nickname = "([^"]+)"',
        r'<span[^>]*class="profile_nickname"[^>]*>(.*?)</span>',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            candidate = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if candidate:
                author = candidate
                break

    # Publish time
    publish_time = ""
    m = re.search(r'var ct = "(\d+)"', html)
    if m:
        publish_time = dt.datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d")

    # Content
    content_html = ""
    for pat in [
        r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*</div>',
        r'<div[^>]*class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script',
    ]:
        m = re.search(pat, html, re.DOTALL)
        if m:
            content_html = m.group(1)
            break

    if not content_html:
        record["note"] = "content-not-found"
        return record

    # Extract image URLs (data-src = lazy loaded real URL)
    image_urls = []
    for m in re.finditer(r'<img[^>]+data-src="([^"]+)"', content_html):
        u = m.group(1)
        if u.startswith('http') and 'mmbiz' in u and u not in image_urls:
            image_urls.append(u)

    # Fallback: src attribute
    if not image_urls:
        for m in re.finditer(r'<img[^>]+src="([^"]+)"', content_html):
            u = m.group(1)
            if u.startswith('http') and 'mmbiz' in u and u not in image_urls:
                image_urls.append(u)

    # Download images
    downloaded_images = []
    for i, img_url in enumerate(image_urls, 1):
        try:
            # Determine format and add wx_fmt for consistent output
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
                downloaded_images.append((i, target.name, dl["bytes"]))
                content_html = content_html.replace(img_url, target.name)
                if full_url != img_url:
                    content_html = content_html.replace(full_url, target.name)
        except Exception:
            continue

    # Convert to markdown
    content_md = html_to_markdown(content_html)

    # Save output
    title_safe = safe_filename(title[:60], "wechat-article")
    author_safe = safe_filename(author, "wechat")
    md_path = out_dir / f"{author_safe}_《{title_safe}》_公众号文章.md"

    full_md = build_article_md(
        title=title, author=author, url=url, platform="微信公众号",
        content_md=content_md, image_count=len(downloaded_images),
        publish_time=publish_time,
    )
    md_path.write_text(full_md, encoding="utf-8")

    # Record
    all_files = [str(md_path)] + [str(out_dir / n) for _, n, _ in downloaded_images]
    total_bytes = sum(s for _, _, s in downloaded_images) + md_path.stat().st_size

    record["status"] = "ok"
    record["files"] = all_files
    record["bytes"] = total_bytes
    record["note"] = f"{len(content_md)}字, {len(downloaded_images)}图"

    # Save metadata
    (out_dir / ".metadata.json").write_text(
        json.dumps({
            "title": title,
            "author": author,
            "url": url,
            "publish_time": publish_time,
            "platform": "微信公众号",
            "word_count": len(content_md),
            "image_count": len(downloaded_images),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return record


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.wechat_article <URL> [output_dir]")
        sys.exit(1)

    url = sys.argv[1]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not out_dir:
        from .utils import make_run_dir
        out_dir = make_run_dir("微信公众号文章")

    out_dir.mkdir(parents=True, exist_ok=True)
    result = extract(url, out_dir)
    write_reports(out_dir, [url], [result])
    print(f"Status: {result['status']}")
    print(f"Files: {len(result['files'])}")
    if result['note']:
        print(f"Note: {result['note']}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    import json
    main()
