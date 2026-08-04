"""
Core utilities shared across all extractors.
"""
import os, re, json, datetime as dt
from pathlib import Path


def safe_filename(text: str, fallback: str = "file", max_len: int = 80) -> str:
    """Sanitize string for use as filename."""
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '_', text or "")
    value = re.sub(r'\s+', ' ', value).strip(' .')
    if len(value) > max_len:
        value = value[:max_len].rstrip(' .')
    return value or fallback


def get_output_root() -> Path:
    """Resolve output root: OUTPUT_ROOT env var > cwd/Outputs/"""
    env_root = os.environ.get("OUTPUT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.cwd() / "Outputs"


def make_run_dir(topic: str = "video-download") -> Path:
    """Create dated output directory: {root}/YYYY-MM-DD-{topic}/"""
    root = get_output_root()
    date = dt.date.today().isoformat()
    candidate = root / f"{date}-{topic}"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def download_with_resume(url: str, target: Path, *, headers: dict = None,
                          timeout: int = 120, max_mb: float = 2000) -> dict:
    """Download a file with resume support via .part file + HTTP Range."""
    import requests
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


def extract_audio(video_path: str, output_wav: str, ffmpeg: str = "ffmpeg") -> float:
    """Extract audio from video as 16kHz mono WAV. Returns duration in seconds."""
    import subprocess
    result = subprocess.run(
        [ffmpeg, "-y", "-i", video_path,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
         output_wav],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

    # Get duration
    probe = subprocess.run(
        [ffmpeg, "-i", output_wav],
        capture_output=True, text=True,
    )
    duration = 0.0
    m = re.search(r'Duration:\s+(\d+):(\d+):(\d+\.\d+)', probe.stderr)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return duration


def transcribe(audio_path: str, model_name: str = "large-v3-turbo",
               language: str = None) -> dict:
    """Transcribe audio with Whisper. Returns {text, segments, language, duration}."""
    os.environ["WHISPER_NO_WSL"] = "1"
    import whisper
    model = whisper.load_model(model_name)
    result = model.transcribe(
        str(audio_path),  # MUST be string, not Path object
        task="transcribe",
        language=language,
        condition_on_previous_text=False,
    )
    return {
        "text": result["text"],
        "segments": result["segments"],
        "language": result.get("language", language or "unknown"),
        "duration": result["segments"][-1]["end"] if result["segments"] else 0,
    }


def _fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


def build_transcript_md(title: str, author: str, url: str, platform: str,
                        language: str, duration_sec: float, segments: list) -> str:
    """Build standard-format transcript Markdown."""
    lines = [
        "# 逐字稿", "",
        "## 元数据",
        f"- **标题**：{title}",
        f"- **作者**：{author}",
        f"- **来源**：<{url}>",
        f"- **平台**：{platform}",
        f"- **语言**：{language}",
        f"- **时长**：{_fmt_time(duration_sec)}",
        f"- **生成时间**：{dt.date.today().isoformat()}",
        "", "---", "",
    ]
    for seg in segments:
        start = _fmt_time(seg["start"])
        end = _fmt_time(seg["end"])
        text = seg["text"].strip()
        if text:
            lines.append(f"[{start} - {end}] {text}")
    return "\n".join(lines) + "\n"


def html_to_markdown(html_content: str) -> str:
    """Basic HTML → Markdown conversion (for articles/posts)."""
    md = html_content

    # Remove script/style
    md = re.sub(r'<script[^>]*>.*?</script>', '', md, flags=re.DOTALL)
    md = re.sub(r'<style[^>]*>.*?</style>', '', md, flags=re.DOTALL)

    # Headings
    for i in range(1, 7):
        md = re.sub(
            f'<h{i}[^>]*>(.*?)</h{i}>',
            lambda m, l=i: '\n\n' + '#' * l + ' ' + re.sub(r'<[^>]+>', '', m.group(1)).strip() + '\n\n',
            md, flags=re.DOTALL)

    # Formatting
    md = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', md, flags=re.DOTALL)
    md = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', md, flags=re.DOTALL)

    # Paragraphs / breaks
    md = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\n\1\n\n', md, flags=re.DOTALL)
    md = re.sub(r'<br\s*/?>', '\n', md)

    # Images
    def _img_repl(m):
        src = m.group(1) or m.group(2)
        alt = m.group(3) if len(m.groups()) >= 3 else ''
        return f'\n\n![{alt}]({src})\n\n'
    md = re.sub(
        r'<img[^>]+(?:data-src|src)="([^"]*)"[^>]*(?:src="([^"]*)")?[^>]*alt="([^"]*)"[^>]*/?>',
        _img_repl, md, flags=re.DOTALL)
    md = re.sub(
        r'<img[^>]+src="([^"]+)"[^>]*/?>',
        lambda m: f'\n\n![]({m.group(1)})\n\n', md)

    # Links
    md = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.DOTALL)

    # Lists
    md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1', md, flags=re.DOTALL)
    md = re.sub(r'</?(ul|ol)[^>]*>', '\n', md)

    # Blockquote / code
    md = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1', md, flags=re.DOTALL)
    md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.DOTALL)
    md = re.sub(r'<pre[^>]*>(.*?)</pre>', r'\n```\n\1\n```\n', md, flags=re.DOTALL)

    # Section divs
    md = re.sub(r'</?(section|div|span)[^>]*>', '', md)

    # HTML entities
    md = md.replace('&nbsp;', ' ').replace('&amp;', '&')
    md = md.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')

    # Clean whitespace
    md = re.sub(r' +\n', '\n', md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()


def build_article_md(title: str, author: str, url: str, platform: str,
                     content_md: str, image_count: int,
                     publish_time: str = "") -> str:
    """Build standard-format article Markdown."""
    lines = [
        f"# {title}", "",
        "## 元数据",
        f"- **标题**：{title}",
        f"- **作者**：{author}",
        f"- **来源**：<{url}>",
        f"- **平台**：{platform}",
    ]
    if publish_time:
        lines.append(f"- **发布时间**：{publish_time}")
    lines += [
        f"- **图片数**：{image_count}",
        f"- **生成时间**：{dt.date.today().isoformat()}",
        "", "---", "",
        "## 正文", "",
        content_md,
    ]
    return "\n".join(lines) + "\n"


def write_reports(out_dir: Path, urls: list, records: list) -> None:
    """Generate both download-report.md and download-report.json."""
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

    ok = sum(1 for r in records if r.get("status") == "ok")
    skipped = sum(1 for r in records if r.get("status") == "skipped")
    failed = len(records) - ok - skipped

    def _size_text(n):
        if not n: return ""
        units = ["B", "KB", "MB", "GB"]
        v = float(n)
        for u in units:
            if v < 1024 or u == units[-1]:
                return f"{v:.1f} {u}" if u != "B" else f"{int(v)} B"
            v /= 1024
        return f"{n} B"

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
