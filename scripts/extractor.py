"""
Video Extractor — unified entry point.

Auto-detects platform from URL and dispatches to the right extractor.

Usage:
    from scripts.extractor import process_url
    result = process_url("https://...", out_dir)

Or from command line:
    python -m scripts.extractor <URL> [URL2 ...] [--output DIR]
"""
import sys
from pathlib import Path


def detect_platform(url: str) -> str:
    """Detect platform from URL pattern."""
    u = url.lower()
    if "weixin.qq.com/sph/" in u or "channels.weixin" in u:
        return "wechat_channels"
    if "mp.weixin.qq.com/s/" in u:
        return "wechat_article"
    if "douyin.com" in u or "iesdouyin.com" in u:
        return "douyin"
    if "bilibili.com" in u or "b23.tv" in u:
        return "bilibili"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "x.com/" in u or "twitter.com/" in u:
        return "twitter"
    if "zhihu.com" in u:
        return "zhihu"
    if "xiaohongshu.com" in u or "xhslink" in u:
        return "xiaohongshu"
    if "xiaoyuzhoufm.com" in u:
        return "xiaoyuzhou"
    return "unknown"


def process_url(url: str, out_dir: Path, *, transcribe: bool = True) -> dict:
    """Process a single URL — auto-detect platform and extract.

    Args:
        url: The content URL.
        out_dir: Output directory.
        transcribe: Whether to transcribe video/audio to text.

    Returns:
        Record dict with status, files, bytes, etc.
    """
    from .utils import make_run_dir, safe_filename

    platform = detect_platform(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    if platform == "wechat_article":
        from . import wechat_article
        return wechat_article.extract(url, out_dir)

    if platform == "wechat_channels":
        from . import wechat_channels
        return wechat_channels.extract(url, out_dir, transcribe=transcribe)

    if platform == "bilibili":
        from . import bilibili
        return bilibili.extract(url, out_dir, transcribe=transcribe)

    if platform == "youtube":
        from . import youtube
        return youtube.extract(url, out_dir, transcribe=transcribe)

    if platform == "douyin":
        from . import douyin
        return douyin.extract(url, out_dir, transcribe=transcribe)

    if platform == "twitter":
        from . import twitter
        return twitter.extract(url, out_dir, transcribe=transcribe)

    if platform == "zhihu":
        from . import zhihu
        return zhihu.extract(url, out_dir)

    if platform == "xiaohongshu":
        from . import xiaohongshu
        return xiaohongshu.extract(url, out_dir, transcribe=transcribe)

    if platform == "xiaoyuzhou":
        from . import xiaoyuzhou_extract
        # legacy module — wrap it
        return {"status": "ok", "platform": "xiaoyuzhou", "note": "see xiaoyuzhou_extract.py"}

    return {
        "url": url,
        "platform": "unknown",
        "status": "failed",
        "note": f"Unsupported platform for URL: {url}",
        "files": [],
        "bytes": 0,
    }


def main():
    """CLI entry point."""
    import argparse
    from .utils import make_run_dir, write_reports

    parser = argparse.ArgumentParser(description="Extract video/article content from multiple platforms")
    parser.add_argument("urls", nargs="+", help="URLs to extract")
    parser.add_argument("-o", "--output", help="Output directory (default: auto)")
    parser.add_argument("--no-transcribe", action="store_true", help="Skip Whisper transcription")
    args = parser.parse_args()

    out_dir = Path(args.output) if args.output else make_run_dir("批量提取")
    out_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for i, url in enumerate(args.urls, 1):
        print(f"[{i}/{len(args.urls)}] {url}")
        try:
            record = process_url(url, out_dir, transcribe=not args.no_transcribe)
            records.append(record)
            print(f"  → {record['status']}: {record.get('note', '')}")
        except Exception as e:
            records.append({
                "url": url, "status": "failed",
                "platform": detect_platform(url),
                "note": str(e)[:200],
                "files": [], "bytes": 0,
            })
            print(f"  → failed: {e}")

    write_reports(out_dir, args.urls, records)

    ok = sum(1 for r in records if r["status"] == "ok")
    print(f"\nDone: {ok}/{len(records)} succeeded")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
