#!/usr/bin/env python3
"""
Extract comments from video platforms using Playwright browser automation.
Supports: Douyin, Bilibili, XiaoHongShu, YouTube.

Usage:
    python extract_comments.py "VIDEO_URL" --platform douyin --max-scrolls 15
    python extract_comments.py "VIDEO_URL" --platform bilibili --max-scrolls 10
    python extract_comments.py "VIDEO_URL" --platform youtube
    python extract_comments.py "VIDEO_URL" --auto  # auto-detect platform
"""

import asyncio
import argparse
import json
import sys
from urllib.parse import urlparse


def detect_platform(url: str) -> str:
    """Auto-detect platform from URL."""
    host = urlparse(url).hostname or ""
    if "douyin.com" in host or "iesdouyin.com" in host:
        return "douyin"
    elif "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    elif "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    elif "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xiaohongshu"
    else:
        raise ValueError(f"Cannot detect platform from URL: {url}")


# --- Platform-specific comment parsers ---

def parse_douyin_comment(c: dict) -> dict:
    user = c.get("user", {})
    return {
        "user": user.get("nickname", "") if isinstance(user, dict) else "",
        "text": c.get("text", ""),
        "likes": c.get("digg_count", 0),
        "replies": c.get("reply_comment_total", 0),
        "reply_list": [
            {
                "user": r.get("user", {}).get("nickname", "") if isinstance(r.get("user"), dict) else "",
                "text": r.get("text", ""),
                "likes": r.get("digg_count", 0),
            }
            for r in (c.get("reply_comment", []) or [])
        ],
    }


def parse_bilibili_comment(c: dict) -> dict:
    return {
        "user": c.get("member", {}).get("uname", ""),
        "text": c.get("content", {}).get("message", ""),
        "likes": c.get("like", 0),
        "replies": c.get("rcount", 0),
        "reply_list": [
            {
                "user": r.get("member", {}).get("uname", ""),
                "text": r.get("content", {}).get("message", ""),
                "likes": r.get("like", 0),
            }
            for r in (c.get("replies", []) or [])
        ],
    }


# --- Comment extraction via Playwright ---

# URL patterns that indicate comment API responses
COMMENT_URL_PATTERNS = {
    "douyin": ["comment/list", "comment_list"],
    "bilibili": ["reply", "comment"],
    "xiaohongshu": ["comment"],
    "youtube": [],  # Use yt-dlp instead
}

COMMENT_PARSERS = {
    "douyin": parse_douyin_comment,
    "bilibili": parse_bilibili_comment,
}

# JSON path to comments array in API response
COMMENTS_PATH = {
    "douyin": lambda d: d.get("comments", []),
    "bilibili": lambda d: (d.get("data", {}).get("replies", []) or []),
    "xiaohongshu": lambda d: (d.get("data", {}).get("comments", []) or []),
}


async def extract_comments(url: str, platform: str, max_scrolls: int = 15) -> list:
    """Extract comments using Playwright browser automation."""
    from playwright.async_api import async_playwright

    if platform == "youtube":
        print("YouTube:推荐使用 yt-dlp --write-comments 提取评论", file=sys.stderr)
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = await context.new_page()

        comments = []
        seen_ids = set()
        url_patterns = COMMENT_URL_PATTERNS.get(platform, [])
        parser = COMMENT_PARSERS.get(platform, parse_douyin_comment)
        get_comments = COMMENTS_PATH.get(platform, lambda d: d.get("comments", []))

        async def handle_response(response):
            resp_url = response.url
            if any(pat in resp_url for pat in url_patterns) and response.status == 200:
                try:
                    data = await response.json()
                    for c in get_comments(data):
                        cid = c.get("cid", "") or c.get("rpid", "") or str(id(c))
                        if cid not in seen_ids:
                            seen_ids.add(cid)
                            comments.append(parser(c))
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"Navigating to {url}...", file=sys.stderr)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation warning (continuing): {e}", file=sys.stderr)

        await asyncio.sleep(8)
        print(f"Initial load: {len(comments)} comments", file=sys.stderr)

        # Scroll to load more comments
        for i in range(max_scrolls):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1.5)
            print(f"Scroll {i+1}/{max_scrolls}: {len(comments)} comments", file=sys.stderr)

        await browser.close()

    return sorted(comments, key=lambda x: x["likes"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Extract video comments via Playwright")
    parser.add_argument("url", help="Video URL")
    parser.add_argument("--platform", choices=["douyin", "bilibili", "youtube", "xiaohongshu", "auto"],
                        default="auto", help="Platform (default: auto-detect)")
    parser.add_argument("--max-scrolls", type=int, default=15, help="Max scroll iterations (default: 15)")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    args = parser.parse_args()

    platform = args.platform
    if platform == "auto":
        platform = detect_platform(args.url)
    print(f"Detected platform: {platform}", file=sys.stderr)

    comments = asyncio.run(extract_comments(args.url, platform, args.max_scrolls))

    output = json.dumps(comments, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved {len(comments)} comments to {args.output}", file=sys.stderr)
    else:
        print(output)

    print(f"Total: {len(comments)} comments", file=sys.stderr)


if __name__ == "__main__":
    main()
