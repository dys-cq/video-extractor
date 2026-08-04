# video-extractor

一键提取多平台视频/图文内容 + Whisper 语音转录（简体中文原生输出）。

## 支持平台

| 平台 | 支持内容 |
|------|---------|
| YouTube | 视频 + 逐字稿 |
| B站 | 视频 + 高音质音频 + 逐字稿 |
| 微信视频号 | 视频（H264+H265 双版本）+ 逐字稿 |
| 微信公众号 | 文章全文 + 高清图片 |
| 小红书 | 视频/图文 + 逐字稿 |
| 抖音 | 视频 + 逐字稿 |
| X/Twitter | 视频/图文/纯文字 + 逐字稿 |
| 知乎 | 回答/专栏文章 + 高清图片 |
| 小宇宙播客 | 音频 + 逐字稿 |

## 功能特性

- 🎯 **统一输出格式**：所有平台逐字稿格式完全一致（中文元数据 + MM:SS 时间戳）
- 📊 **任务报告**：自动生成 download-report.md + json
- 🔄 **断点续传**：`.part` 文件支持，断网了续传
- 📦 **下载去重**：download-archive.txt 避免重复下载
- 📁 **规范目录结构**：`Outputs/YYYY-MM-DD-{主题}/`
- 🇨🇳 **简体中文原生输出**：large-v3-turbo 模型，无需繁简转换

## 安装

### 系统要求

- **Python** 3.10+
- **FFmpeg** — 音频/视频处理，Whisper 依赖
- **Chrome / Chromium** — Playwright 会自动下载

### 详细安装步骤

#### 1. Python 包

```bash
pip install yt-dlp openai-whisper requests playwright
python -m playwright install chromium
```

#### 2. 安装 FFmpeg

**FFmpeg 是必须的** — Whisper 调用它来处理音频，下载视频后也需要它来提取音轨。

##### macOS

```bash
# 最简单 — 用 Homebrew
brew install ffmpeg

# 验证安装
ffmpeg -version
```

如果没有 Homebrew：先去 https://brew.sh 装一下，或者去 https://evermeet.cx/ffmpeg/ 下载静态编译版放到 `/usr/local/bin/`。

##### Linux (Debian / Ubuntu)

```bash
sudo apt update
sudo apt install ffmpeg

# 验证安装
ffmpeg -version
```

其他发行版用对应的包管理器：
- Fedora / RHEL: `sudo dnf install ffmpeg`
- Arch: `sudo pacman -S ffmpeg`

##### Windows

**方式一：直接下载（推荐新手）**

1. 去 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`
2. 解压到一个固定目录，比如 `C:\ffmpeg\`
3. 把 `C:\ffmpeg\bin\` 加到系统环境变量 PATH 里
4. 打开新的命令行，验证：
   ```cmd
   ffmpeg -version
   ```

**方式二：用 Chocolatey**

```powershell
# 先装 Chocolatey (https://chocolatey.org/)
choco install ffmpeg
ffmpeg -version
```

**方式三：用 Scoop**

```powershell
scoop install ffmpeg
```

> ⚠️ 验证安装成功后再继续。Whisper 在导入和转录时都会调用 FFmpeg，如果找不到会直接报错。

#### 3. 环境变量配置

大部分情况下不需要手动配置环境变量，默认安装就能用。但下面这些是**可选/按需配置**的：

| 环境变量 | 是否必须 | 作用 | 建议值 |
|---------|---------|------|--------|
| **PATH** (含 ffmpeg) | ✅ 必须 | 让 Python/Whisper 能找到 ffmpeg 命令 | FFmpeg 的 `bin` 目录路径 |
| **PATH** (含 yt-dlp) | 可选 | `pip install` 后一般已经在 PATH 里了 | 不需要额外配置 |
| `WHISPER_NO_WSL` | Windows 必须 | 禁止 Whisper 弹出 WSL 安装窗口 | `1` |
| `OUTPUT_ROOT` | 可选 | 自定义输出根目录 | 如 `D:\VideoExtract\Outputs` |
| `PYTHONUTF8` | Linux 服务器推荐 | 确保中文文件名正常 | `1` |

##### Windows 环境变量设置方法

**方式一：系统设置（永久）**

1. Win + S 搜索「环境变量」→ 编辑系统环境变量
2. 点击「环境变量」按钮
3. 在「系统变量」里找到 `Path` → 编辑 → 新建 → 粘贴 FFmpeg 的 bin 目录路径（如 `C:\ffmpeg\bin`）
4. 确定保存，**重启命令行**后生效

**方式二：代码里临时设置（推荐，不污染系统）**

```python
import os

# 修复 WSL 弹窗
os.environ["WHISPER_NO_WSL"] = "1"

# 如果 ffmpeg 不在 PATH 里，手动指定目录
ffmpeg_dir = r"C:\Users\yourname\software\ffmpeg\bin"
os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
```

##### macOS / Linux 环境变量设置

把下面这些加到 `~/.zshrc` 或 `~/.bashrc` 里：

```bash
# 如果 ffmpeg 是 brew 装的，通常已经在 PATH 里了，不需要额外配置
# 自定义输出目录
export OUTPUT_ROOT="$HOME/VideoExtract/Outputs"

# 服务器环境建议
export PYTHONUTF8=1
```

> 💡 **Whisper 和 yt-dlp 都是 pip 装的 Python 包**，安装后自动在 Python 环境里可用，不需要单独配置环境变量。只有 FFmpeg 是外部二进制程序，需要确保在 PATH 中。

### Windows 额外注意

Whisper 在 Windows 上会弹 WSL 安装窗口，代码里已经处理了（自动设置 `WHISPER_NO_WSL=1` 环境变量），无需手动操作。

### macOS 额外注意

- 建议用 Homebrew 安装 FFmpeg：`brew install ffmpeg`
- Apple Silicon Mac 上 Whisper 可以用 MPS 加速（`mps` 设备），但 `large-v3-turbo` 可能显存不够，需要看具体机型
- 没有 NVIDIA GPU 的话转录会慢一些（CPU 或 MPS）

### Linux 额外注意

- FFmpeg：`sudo apt install ffmpeg`（Debian/Ubuntu）或对应发行版的包管理器
- 有 NVIDIA GPU 的话确保装好 CUDA 驱动，Whisper 会自动检测并使用
- 服务器环境注意设置 `PYTHONUTF8=1`

## 快速开始

```python
from pathlib import Path
import sys

# 导入微信视频号模块（根据实际路径调整）
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from wx_channels import fetch_wx_channels

# 创建输出目录
out_dir = Path("./Outputs/2026-08-03-测试")
out_dir.mkdir(parents=True, exist_ok=True)

# 下载视频
result = fetch_wx_channels(
    "https://weixin.qq.com/sph/xxxxxx",
    out_dir
)
print(result["status"])  # ok / failed
print(result["files"])   # 下载的文件列表
```

## 输出格式

```
# macOS / Linux
Outputs/2026-08-03-主题/
├── {作者}_《{标题}》_video.mp4
├── {作者}_《{标题}》.wav
├── {作者}_《{标题}》_逐字稿.md
├── download-report.md
├── download-report.json
└── .metadata.json

# Windows
Outputs\2026-08-03-主题\
├── {作者}_《{标题}》_video.mp4
├── ...
```

> 代码内部使用 `pathlib.Path`，自动适配各系统的路径分隔符。

### 逐字稿格式

```markdown
# 逐字稿

## 元数据
- **标题**：xxx
- **作者**：xxx
- **来源**：<URL>
- **平台**：YouTube / 抖音 / B站 / ...
- **语言**：zh
- **时长**：5:17
- **生成时间**：2026-08-03

---

[00:00 - 00:03] 第一段文字内容
[00:03 - 00:07] 第二段文字内容
...
```

## 项目结构

```
video-extractor/
├── SKILL.md                          # 技能说明文档 (Hermes 技能格式)
├── README.md                         # 用户文档 (本文档)
├── DEVELOPMENT.md                    # 开发文档
├── references/
│   └── platforms.md                  # 各平台详细实现参考
└── scripts/
    ├── transcribe_windows.py         # Windows 优化的转录脚本
    ├── merge_chunks.py               # 分段合并 + 时间戳修正
    ├── extract_comments.py           # 评论提取
    ├── traditional_to_simplified.py  # 繁简转换（备用）
    └── xiaoyuzhou_extract.py         # 小宇宙播客提取
```

> 所有路径操作都使用 `pathlib.Path`，兼容 Windows / macOS / Linux。

## 许可证

MIT
