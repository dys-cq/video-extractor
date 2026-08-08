"""
Douyin (抖音) video extractor.

Douyin has strong anti-bot protection — direct API calls and HTML scraping
both fail. Primary method: Playwright API interception of the `aweme/detail`
XHR response to get the real video URL.

Usage:
    from scripts.douyin import extract
    result = extract("https://v.douyin.com/xxxx/", out_dir, transcribe=True)
"""
import os, re, json, datetime as dt
from pathlib import Path
import requests

from .utils import (
    safe_filename, extract_audio, transcribe, build_transcript_md,
    write_reports,
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def can_handle(url: str) -> bool:
    return "douyin.com" in url or "iesdouyin.com" in url


def dedup_title(title: str) -> str:
    """Remove duplicated title halves (Douyin desc sometimes repeats itself)."""
    t = (title or "").strip()
    half = len(t) // 2
    if half > 5 and t[:half] == t[half:]:
        return t[:half]
    # "ABC ABC" style with space separator
    parts = re.split(r'[\s,，。]+', t)
    if len(parts) >= 2 and parts[0] == parts[1]:
        return t[len(parts[0]) + 1:]
    return t


def _intercept_video_url(short_url: str, timeout_ms: int = 6000) -> tuple:
    """Launch Playwright, intercept aweme API response, return (video_url, author, title)."""
    from playwright.sync_api import sync_playwright

    video_url, author, title = None, "", ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 720})

        def handle_response(resp):
            nonlocal video_url, author, title
            u = resp.url
            if "aweme" in u and ("detail" in u or "post" in u or "feed" in u):
                try:
                    data = resp.json()
                    detail = data.get("aweme_detail") or (data.get("aweme_list") or [{}])[0] or {}
                    if detail:
                        t = (detail.get("desc") or "").strip()[:100]
                        if t:
                            title = t
                        a = detail.get("author", {}).get("nickname", "")
                        if a:
                            author = a
                        urls = detail.get("video", {}).get("play_addr", {}).get("url_list", [])
                        if urls:
                            video_url = urls[0]
                except Exception:
                    pass

        page = context.new_page()
        page.on("response", handle_response)
        page.goto(short_url, timeout=30000)
        page.wait_for_timeout(timeout_ms)

        # Fallback: <video> element src
        if not video_url:
            for v in page.query_selector_all("video"):
                src = v.get_attribute("src")
                if src:
                    video_url = src
                    break

        browser.close()
    return video_url, author, title


def extract(url: str, out_dir: Path, *, transcribe: bool = True, ffmpeg: str = "ffmpeg") -> dict:
    """Extract Douyin video: download + audio + Whisper transcript.

    Returns a record dict with status, files, bytes, etc.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "url": url, "kind": "douyin", "platform": "抖音",
        "status": "failed", "files": [], "bytes": 0, "note": "",
    }

    # Step 1: intercept video URL
    video_url, author, title = _intercept_video_url(url)
    title = dedup_title(title)

    if not video_url:
        record["note"] = "video-url-not-found (anti-bot interception failed)"
        return record

    # Step 2: download video
    author_safe = safe_filename(author, "抖音用户")
    title_safe = safe_filename(title[:50], "抖音视频")
    video_path = out_dir / f"{author_safe}_《{title_safe}》_video.mp4"

    resp = requests.get(video_url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"},
                        stream=True, timeout=120)
    video_size = 0
    with open(video_path, "wb") as f:
        for chunk in resp.iter_content(64 * 1024):
            if chunk:
                f.write(chunk)
                video_size += len(chunk)

    files = [str(video_path)]

    # Step 3: audio
    wav_path = out_dir / f"{author_safe}_《{title_safe}》.wav"
    duration = 0
    if transcribe:
        try:
            duration = extract_audio(str(video_path), str(wav_path), ffmpeg=ffmpeg)
            files.append(str(wav_path))
        except Exception as e:
            record["note"] = f"audio-extract-failed: {str(e)[:100]}"

    # Step 4: transcript
    seg_count = 0
    if transcribe and wav_path.exists():
        try:
            tr = transcribe(str(wav_path))
            segments = tr["segments"]
            seg_count = sum(1 for s in segments if s["text"].strip())
            md_path = out_dir / f"{author_safe}_《{title_safe}》_逐字稿.md"
            md_path.write_text(
                build_transcript_md(
                    title=title, author=author, url=url, platform="抖音",
                    language=tr.get("language", "zh"), duration_sec=duration,
                    segments=segments,
                ),
                encoding="utf-8",
            )
            files.append(str(md_path))
        except Exception as e:
            record["note"] = f"transcribe-failed: {str(e)[:100]}"

    # Step 5: metadata + reports
    total_bytes = sum(Path(f).stat().st_size for f in files if Path(f).exists())
    record["status"] = "ok"
    record["files"] = files
    record["bytes"] = total_bytes
    record["note"] = (record["note"] or "") + f"{seg_count}段, {int(duration)}s"

    (out_dir / ".metadata.json").write_text(
        json.dumps({"title": title, "author": author, "url": url, "platform": "抖音",
                    "duration": int(duration), "segment_count": seg_count},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_reports(out_dir, [url], [record])
    return record


def main():
    import sys
    from .utils import make_run_dir
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.douyin <URL> [--no-transcribe]")
        sys.exit(1)
    url = sys.argv[1]
    transcribe_flag = "--no-transcribe" not in sys.argv
    out_dir = make_run_dir("抖音视频")
    result = extract(url, out_dir, transcribe=transcribe_flag)
    print(f"Status: {result['status']}")
    print(f"Note: {result.get('note')}")
    for f in result["files"]:
        print(f"  - {Path(f).name}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
