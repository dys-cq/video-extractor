# -*- coding: utf-8 -*-
"""
纯机械合并分块转录结果，不做任何文字修改。
1. 自动发现目录下所有 chunk_*_result.txt 文件
2. 按序号排序，纯文本拼接
3. 修正每个块的时间戳偏移（chunk_N + N×600秒）
4. 转换为 HH:MM:SS 格式输出
"""
import os
import re
import sys
from pathlib import Path


def find_chunk_files(directory: Path) -> list:
    """按序号顺序找到所有分块文件"""
    chunk_files = []
    for f in directory.glob("chunk_*_result.txt"):
        match = re.search(r"chunk_(\d+)_result", f.name)
        if match:
            chunk_num = int(match.group(1))
            chunk_files.append((chunk_num, f))
    return [f for _, f in sorted(chunk_files, key=lambda x: x[0])]


def seconds_to_hhmmss(seconds: float) -> str:
    """秒数转 HH:MM:SS 格式"""
    sec = int(seconds)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def process_line(line: str, offset: int) -> str:
    """处理单行：偏移时间戳 + 转换为 HH:MM:SS 格式"""
    # 匹配 [秒数-秒数] 格式
    match = re.match(r"\[(\d+\.?\d*)\-(\d+\.?\d*)\](.*)", line)
    if match:
        start_sec = float(match.group(1)) + offset
        end_sec = float(match.group(2)) + offset
        start_hhmmss = seconds_to_hhmmss(start_sec)
        end_hhmmss = seconds_to_hhmmss(end_sec)
        content = match.group(3)
        return f"[{start_hhmmss} - {end_hhmmss}]{content}"
    return line


def merge_chunks(directory: Path, output_file: Path = None) -> Path:
    """合并所有分块，修正时间戳"""
    chunk_files = find_chunk_files(directory)
    if not chunk_files:
        raise ValueError(f"在 {directory} 未找到任何 chunk_*_result.txt 文件")
    
    print(f"发现 {len(chunk_files)} 个分块文件")
    
    result_lines = []
    for i, chunk_file in enumerate(chunk_files):
        offset = i * 600  # 每个块 10 分钟 = 600 秒
        print(f"处理第 {i} 块 (偏移 +{offset} 秒)...")
        
        with open(chunk_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()
                if line.strip():
                    result_lines.append(process_line(line, offset))
    
    # 输出文件名
    if not output_file:
        output_file = directory / "完整转录_时间戳已对齐.md"
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# 完整逐字转录结果（已修正时间戳）\n\n")
        f.write(f"分块数：{len(chunk_files)}\n")
        f.write(f"说明：所有时间戳已偏移修正并转换为 HH:MM:SS 格式\n\n")
        f.write("---\n\n")
        for line in result_lines:
            f.write(line + "\n")
    
    print(f"\n✅ 合并完成！共 {len(result_lines)} 行")
    print(f"📄 输出文件：{output_file}")
    return output_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python merge_chunks.py <分块目录> [输出文件路径]")
        sys.exit(1)
    
    directory = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    merge_chunks(directory, output_file)
