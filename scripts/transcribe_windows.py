# -*- coding: utf-8 -*-
"""
Windows 环境下专用的 Whisper 分块转录脚本
专门解决 WSL 弹窗干扰、长音频内存不足、Hermes TUI 输出拦截等问题
"""
import os
import sys
import subprocess
from pathlib import Path

# === 阻止 WSL 干扰（Windows 必须）===
for key in list(os.environ.keys()):
    if "WSL" in key.upper():
        del os.environ[key]
os.environ["WHISPER_NO_WSL"] = "1"

import whisper

# === 配置 ===
FFMPEG_PATH = r"C:\Users\Administrator\Documents\software\ffmpeg\bin\ffmpeg.exe"
DEFAULT_CHUNK_MINUTES = 10  # 最稳定的分块大小


def get_audio_duration(wav_path: Path) -> float:
    """获取音频时长（秒）"""
    result = subprocess.run(
        [FFMPEG_PATH.replace("ffmpeg.exe", "ffprobe.exe"),
         "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def split_audio(wav_path: Path, output_dir: Path, chunk_minutes: int = DEFAULT_CHUNK_MINUTES) -> list:
    """将长音频切成多个 10 分钟块"""
    duration = get_audio_duration(wav_path)
    chunk_sec = chunk_minutes * 60
    num_chunks = int(duration // chunk_sec) + 1
    
    print(f"音频总时长：{duration/60:.1f} 分钟，切成 {num_chunks} 个分块")
    
    chunk_files = []
    for i in range(num_chunks):
        start = i * chunk_sec
        chunk_file = output_dir / f"chunk_{i}.wav"
        subprocess.run([
            FFMPEG_PATH, "-y", "-ss", str(start), "-t", str(chunk_sec),
            "-i", str(wav_path), str(chunk_file)
        ], check=True, capture_output=True)
        chunk_files.append(chunk_file)
        print(f"✅ 分块 {i}/{num_chunks-1} 完成")
    
    return chunk_files


def transcribe_chunk(chunk_file: Path, model_name: str = "large-v3-turbo") -> Path:
    """转录单个分块（使用纯命令行 whisper，避免 import 时的 WSL 弹窗）"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    output_dir = chunk_file.parent
    result = subprocess.run(
        ["whisper", str(chunk_file), "--language", "zh", "--model", model_name,
         "--output_dir", str(output_dir), "--output_format", "txt",
         "--condition_on_previous_text", "False"],
        env=env, capture_output=True, text=True
    )
    
    # 重命名结果文件
    txt_file = output_dir / f"{chunk_file.stem}.txt"
    final_file = output_dir / f"{chunk_file.stem}_result.txt"
    if txt_file.exists():
        txt_file.rename(final_file)
        print(f"✅ 分块 {chunk_file.stem} 转录完成")
    else:
        print(f"⚠️ 警告: {txt_file} 未生成")
    
    return final_file


def transcribe_long_audio(wav_path: Path, output_dir: Path = None,
                          model_name: str = "large-v3-turbo",
                          chunk_minutes: int = DEFAULT_CHUNK_MINUTES) -> list:
    """
    转录长音频（自动分块）
    - large-v3-turbo: 原生简体中文，无需繁简转换（推荐）
    - base/small: 可能输出繁体，需要后续繁简转换
    """
    wav_path = Path(wav_path)
    if output_dir is None:
        output_dir = wav_path.parent / "transcription_chunks"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 分块
    chunk_files = split_audio(wav_path, output_dir, chunk_minutes)
    
    # 2. 逐块转录
    result_files = []
    for i, chunk_file in enumerate(chunk_files):
        print(f"\n{'='*60}")
        print(f"正在转录第 {i}/{len(chunk_files)-1} 分块...")
        print(f"{'='*60}")
        result_file = transcribe_chunk(chunk_file, model_name)
        result_files.append(result_file)
    
    print(f"\n✅ 全部转录完成！共 {len(result_files)} 个分块")
    print(f"📁 输出目录：{output_dir}")
    print("\n接下来请使用 merge_chunks.py 合并分块并修正时间戳：")
    print(f"   python scripts/merge_chunks.py \"{output_dir}\"")
    
    return result_files


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Windows 分块转录工具")
    parser.add_argument("wav_path", help="WAV 音频文件路径")
    parser.add_argument("--model", "-m", default="large-v3-turbo",
                       help="Whisper 模型 (large-v3-turbo=原生简体，base/small=快但可能需繁简转换)")
    parser.add_argument("--chunk-minutes", "-c", type=int, default=10, help="分块时长（分钟）")
    parser.add_argument("--output", "-o", help="输出目录")
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else None
    transcribe_long_audio(args.wav_path, output_dir, args.model, args.chunk_minutes)
