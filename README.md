# video-extractor

从抖音、B站、YouTube、小红书、微信视频号、X/Twitter、知乎、小宇宙等平台提取视频、音频、逐字稿和图文内容。

## 特性

- 🎯 **多平台支持** — 抖音、B站、YouTube、小红书、微信视频号/公众号、X/Twitter、知乎、小宇宙播客
- 🎙️ **高质量转录** — 使用 Whisper large-v3-turbo 模型，原生简体中文输出，无需繁简转换
- ⚡ **GPU 加速** — RTX 3080 约 10 倍实时速度
- 📦 **断点续传** — 支持 .part 文件续传和下载存档
- 🔧 **灵活的平台策略** — 每个平台使用最优方案（yt-dlp / Playwright / 直连API / 在线解析）

## 支持平台

| 平台 | 视频 | 音频 | 逐字稿 | 图文/文章 |
|------|------|------|--------|----------|
| YouTube | ✅ | ✅ | ✅ | - |
| Bilibili | ✅ | ✅ | ✅ | - |
| B站课堂 (PUGV) | ✅ | ✅ | ✅ | - |
| 微信视频号 | ✅ | ✅ | ✅ | - |
| 微信公众号 | - | - | - | ✅ |
| 小红书 | ✅ | ✅ | ✅ | ✅ |
| 抖音 | ✅ | ✅ | ✅ | - |
| X/Twitter | ✅ | ✅ | ✅ | ✅ |
| 知乎 | - | - | - | ✅ |
| 小宇宙播客 | ✅ | ✅ | ✅ | ✅ |
| 本地视频/音频 | ✅ | ✅ | ✅ | - |

## 输出格式

所有平台统一输出格式：

```
{output_root}/YYYY-MM-DD-{topic}/
├── {author}_《{title}》.mp4              # 视频文件
├── {author}_《{title}》.wav              # 提取的音频 (16kHz mono)
├── {author}_《{title}》_逐字稿.md          # 带时间戳的逐字稿
├── download-report.md                     # 任务报告
├── download-report.json                   # 机器可读报告
└── .metadata.json                         # 原始元数据
```

逐字稿标准格式：

```markdown
# 逐字稿

## 元数据
- **标题**：...
- **作者**：...
- **来源**：<...>
- **平台**：...
- **语言**：中文
- **时长**：MM:SS
- **生成时间**：YYYY-MM-DD

---

[00:00 - 00:04] 第一段文字内容
[00:04 - 00:07] 第二段文字内容
```

## 环境要求

- Python 3.10+
- ffmpeg
- NVIDIA GPU (推荐，用于Whisper加速)

### Python 依赖

```bash
pip install openai-whisper yt-dlp playwright requests
python -m playwright install chromium
```

## 使用

这是一个 [Hermes Agent](https://github.com/nousresearch/hermes-agent) Skill，支持所有兼容 SKILL.md 的 Agent 环境。

在 Hermes 中直接用自然语言触发，例如：
- "下载这个B站视频并转录"
- "提取这个公众号文章"
- "把这个抖音视频的逐字稿做出来"
- "批量下载这个合集中的所有视频"
- "转录这个本地视频"

## 项目结构

```
video-extractor/
├── SKILL.md                      # Skill 主文档
├── scripts/
│   ├── __init__.py               # 包入口 (process_url / detect_platform)
│   ├── extractor.py              # 主提取器（URL → 平台分发）
│   ├── utils.py                  # 工具函数（下载/转录/报告/HTML转换）
│   ├── douyin.py                 # 抖音提取（Playwright拦截 + 标题去重）
│   ├── wechat_article.py         # 公众号文章提取（3级fallback + 噪声清理）
│   ├── transcribe_windows.py     # Windows分块转录
│   ├── merge_chunks.py           # 分块合并工具
│   ├── xiaoyuzhou_extract.py     # 小宇宙播客提取
│   ├── extract_comments.py       # 评论提取
│   └── traditional_to_simplified.py # 繁简转换（备用）
└── references/
    ├── platforms.md              # 平台细节说明
    └── whisper-windows-wsl-fix.md # Windows WSL弹窗修复
```

## License

MIT
