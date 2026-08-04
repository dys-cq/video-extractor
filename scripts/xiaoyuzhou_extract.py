import argparse
import json
import os
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
import subprocess

# === WINDOWS 适配：清除 WSL 干扰 ===
for key in list(os.environ.keys()):
    if "WSL" in key.upper():
        del os.environ[key]
os.environ["WHISPER_NO_WSL"] = "1"

# === 配置 ===
DEFAULT_OUTPUT_ROOT = Path(r"C:\Users\Administrator\Documents\小宇宙播客")
WHISPER_MODEL = "large-v3-turbo"
FFMPEG_PATH = r"C:\Users\Administrator\Documents\software\ffmpeg\bin\ffmpeg.exe"


def is_xiaoyuzhou_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return "xiaoyuzhoufm.com" in host or "xyzfm.cn" in host


def resolve_short_url(url: str) -> str:
    try:
        resp = requests.head(url, allow_redirects=True, timeout=10)
        return resp.url
    except:
        return url


def extract_episode_id(url: str) -> str:
    match = re.search(r"/episode/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def fetch_episode_metadata(episode_id: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    api_url = f"https://www.xiaoyuzhoufm.com/api/v1/episodes/{episode_id}"
    resp = requests.get(api_url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def download_audio(audio_url: str, output_path: Path) -> Path:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(audio_url, headers=headers, stream=True, timeout=30)
    resp.raise_for_status()
    total_size = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = downloaded / total_size * 100
                    print(f"\r下载进度: {percent:.1f}%", end="", flush=True)
    print()
    return output_path


def convert_to_wav(input_path: Path, output_path: Path) -> Path:
    print(f"转换音频格式...")
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(input_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output_path)],
        check=True, capture_output=True
    )
    return output_path


def transcribe_audio(wav_path: Path, output_dir: Path) -> str:
    """使用 whisper 命令行工具转录，不 import whisper 模块"""
    print(f"\n开始转录 (模型: {WHISPER_MODEL})...")
    print("注意: large-v3-turbo 直接输出简体中文，无需繁简转换")
    
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    subprocess.run(
        ["whisper", str(wav_path), "--language", "zh", "--model", WHISPER_MODEL,
         "--output_dir", str(output_dir), "--output_format", "txt,vtt,srt",
         "--condition_on_previous_text", "False"],
        env=env, check=True
    )
    
    txt_file = output_dir / f"{wav_path.stem}.txt"
    return txt_file.read_text(encoding="utf-8").strip()


def save_markdown(output_dir: Path, title: str, author: str, podcast: str,
                   description: str, transcript: str, metadata: dict) -> Path:
    md_content = f"""# {title}

## 基本信息

- **播客**: {podcast}
- **主播**: {author}
- **时长**: {metadata.get('duration', 0) // 60} 分钟
- **转录模型**: Whisper {WHISPER_MODEL} (直接输出简体中文)
- **原文链接**: {metadata.get('share_url', '')}

## 简介

{description or '无简介'}

---

## 完整文案

{transcript}

---

*本文由 video-extractor Skill 自动转录，使用 large-v3-turbo 模型（原生简体中文输出）*
"""
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:50].strip()
    md_path = output_dir / f"{safe_title}.md"
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


def process_xiaoyuzhou(url: str, output_root: Path = None) -> dict:
    output_root = output_root or DEFAULT_OUTPUT_ROOT
    print("=" * 60)
    print("🎙️  小宇宙播客提取器 (video-extractor Skill)")
    print("=" * 60)
    print(f"原始链接: {url}")
    
    final_url = resolve_short_url(url)
    episode_id = extract_episode_id(final_url)
    if not episode_id:
        raise ValueError(f"无法从 URL 提取单集 ID: {final_url}")
    print(f"单集 ID: {episode_id}")
    
    print("\n📄 获取播客元数据...")
    metadata = fetch_episode_metadata(episode_id)
    title = metadata.get("title", "未知标题")
    author = metadata.get("author", "未知主播")
    podcast = metadata.get("podcast_name", "未知播客")
    description = metadata.get("description", "")
    audio_url = metadata.get("media_url", "")
    if not audio_url:
        raise ValueError("未能获取到音频下载链接")
    print(f"标题: {title}")
    print(f"播客: {podcast}")
    print(f"主播: {author}")
    
    safe_podcast = re.sub(r'[<>:"/\\|?*]', '', podcast)[:30].strip()
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)[:40].strip()
    output_dir = output_root / safe_podcast / safe_title
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 输出目录: {output_dir}")
    
    metadata_file = output_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    print("\n🔊 下载音频...")
    audio_ext = Path(urlparse(audio_url).path).suffix or ".m4a"
    audio_path = output_dir / f"audio{audio_ext}"
    download_audio(audio_url, audio_path)
    print(f"音频已保存: {audio_path.name}")
    
    wav_path = output_dir / "audio.wav"
    convert_to_wav(audio_path, wav_path)
    
    transcript = transcribe_audio(wav_path, output_dir)
    print(f"\n✅ 转录完成，共 {len(transcript)} 字符")
    
    md_path = save_markdown(output_dir, title, author, podcast, description, transcript, metadata)
    
    wav_path.unlink(missing_ok=True)
    
    print("\n" + "=" * 60)
    print("🎉 处理完成！")
    print(f"📄 最终文稿: {md_path}")
    print("=" * 60)
    
    return {"success": True, "title": title, "podcast": podcast, "output_dir": str(output_dir),
            "markdown_file": str(md_path), "audio_file": str(audio_path), "transcript_length": len(transcript)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小宇宙播客提取器 - 使用 large-v3-turbo 原生简体输出")
    parser.add_argument("url", help="小宇宙播客单集链接")
    parser.add_argument("--output", "-o", help="输出根目录")
    parser.add_argument("--check", action="store_true", help="仅检查链接")
    args = parser.parse_args()
    
    if not is_xiaoyuzhou_url(args.url):
        print(f"⚠️  警告: 链接似乎不是小宇宙播客链接")
        sys.exit(1)
    if args.check:
        final_url = resolve_short_url(args.url)
        episode_id = extract_episode_id(final_url)
        print(f"URL 验证通过，单集 ID: {episode_id}")
        sys.exit(0)
    
    output_root = Path(args.output) if args.output else None
    process_xiaoyuzhou(args.url, output_root)
