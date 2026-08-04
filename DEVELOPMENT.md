# 开发文档

本文档详细介绍 video-extractor 技能的设计思路、实现逻辑、踩坑记录和注意事项。

## 目录

1. [架构概览](#架构概览)
2. [平台方法选型矩阵](#平台方法选型矩阵)
3. [核心模块设计](#核心模块设计)
4. [平台实现细节](#平台实现细节)
5. [逐字稿统一格式](#逐字稿统一格式)
6. [Windows 兼容性](#windows-兼容性)
7. [踩坑记录](#踩坑记录)
8. [测试与验证](#测试与验证)

---

## 架构概览

```
用户输入 URL
    │
    ▼
┌─────────────────────────────┐
│  平台识别 (URL pattern 匹配)  │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  对应平台提取器               │
│  (下载视频/图文/音频)         │
└─────────────────────────────┘
    │
    ├─ 视频内容 ─► ffmpeg 提取音频 ─► Whisper 转录 ─► 逐字稿
    │
    └─ 图文内容 ─► 图片下载 + 文字提取 ─► Markdown 输出
    │
    ▼
┌─────────────────────────────┐
│  统一输出 + 报告生成          │
│  (标准命名 + download-report) │
└─────────────────────────────┘
```

### 设计原则

1. **平台优先选择最优方案** — 不搞"一个方案走天下"，每个平台选验证过最好用的方法
2. **输出完全统一** — 不管什么平台，逐字稿格式、命名规范、目录结构都一样
3. **永不空手而归** — 就算视频下载失败，能拿文字拿文字，能拿图片拿图片
4. **失败可恢复** — 断点续传、下载历史、失败重试

---

## 平台方法选型矩阵

| 平台 | 主方案 | 备选方案 | 选型原因 |
|------|--------|----------|---------|
| **YouTube** | yt-dlp | Invidious 代理 (360p) | yt-dlp 对 YouTube 支持最好 |
| **B站** | 直连 playurl API | yt-dlp + cookie | yt-dlp 无 cookie 返回 412；API 虽然只有低清视频但音频质量不受影响 |
| **微信视频号** | 在线解析服务 | 暂无 | 官方无公开 API，第三方服务稳定可用 |
| **小红书** | yt-dlp | Playwright | 意外地好用！全速下载视频 |
| **抖音** | Playwright API 拦截 | yt-dlp + cookie | 反爬强，直连 API 和 yt-dlp 都失败 |
| **X/Twitter** | Playwright | yt-dlp + cookie | yt-dlp 无登录基本不可用 |
| **知乎** | Playwright (非无头+stealth) | 直连 API (常403) | 反爬极强，无头模式会被检测 |
| **小宇宙** | 直连 HTTP 下载 | 无需备选 | 音频公开可访问 |

> **验证状态**：以上所有方案均经过实际测试验证（2026-08-03）。

---

## 核心模块设计

### 1. 输出目录系统

**优先级**：`OUTPUT_ROOT` 环境变量 > `{workspace}/Outputs/`

**目录结构**：
```
{output_root}/YYYY-MM-DD-{topic}/
├── {author}_《{title}》_video.mp4
├── {author}_《{title}》.wav
├── {author}_《{title}》_逐字稿.md
├── download-report.md
├── download-report.json
└── .metadata.json
```

**设计决策**：
- 用日期 + 主题作为顶层目录，方便归档
- 文件名嵌入作者和标题，不依赖目录上下文也能识别
- `.metadata.json` 以下划线开头，在文件管理器里排前面但又不影响正常浏览

### 2. 任务报告系统

每个任务都生成两份报告：
- **download-report.md** — 人读，表格形式
- **download-report.json** — 机器读，结构化数据

**Record 结构**：
```python
{
    "url": "源链接",
    "kind": "platform类型",
    "platform": "平台名",
    "status": "ok|skipped|failed",
    "files": ["文件路径列表"],
    "bytes": 总字节数,
    "note": "备注/失败原因",
}
```

### 3. 断点续传

使用 `.part` 临时文件 + HTTP Range 请求：
1. 如果 `.part` 文件存在，从已下载字节数开始续传
2. 如果服务器不支持 Range (返回 200 而非 206)，从头开始重下
3. 下载完成后 `.part` 重命名为最终文件名

### 4. 下载去重

`download-archive.txt` 记录已完成的 `{platform} {identifier}`，批量任务时跳过已下载的。

---

## 平台实现细节

### 微信视频号

- **方法**：第三方在线解析 `sph.litao.workers.dev`
- **优点**：无需登录、无需装证书、返回 H264+H265 两个版本
- **缺点**：依赖第三方服务可用性
- **参考项目**：ltaoo/wx_channels_download

### B站

- **音频直连方案**：`/x/player/playurl?fnval=16` 返回 DASH 格式
- **关键**：必须带 `Referer: https://www.bilibili.com/` 头，否则 CDN 403
- **无 cookie 限制**：视频只有 32p/16p，但音频最高 162kbps 不受影响

### 抖音

- **反爬特点**：API 需要 X-Bogus 等签名参数，直连失败
- **解决方案**：Playwright 启动真实浏览器，拦截 `aweme/detail` XHR 响应
- **视频 URL**：从 `video.play_addr.url_list[0]` 获取

### X/Twitter

- **三种内容类型**：视频、图文、纯文字
- **决策树**：先找视频 → 再找图片 → 最后保存文字
- **永不空手而归**：就算没视频也保存能拿到的内容

### 知乎

- **反爬最强**：直连 API 403，无头 Playwright 也被检测
- **绕过方法**：非无头模式 + `--disable-blink-features=AutomationControlled` + stealth 脚本
- **stealth 内容**：隐藏 `navigator.webdriver`、伪造 plugins/languages、添加 `window.chrome`
- **图片质量**：`_r.jpg` = 原图质量，要手动替换 `_s.jpg` / `_b.jpg`

### 小红书

- **惊喜发现**：yt-dlp 支持非常好，全速下载
- 图文笔记会被下载成 MP4 幻灯片视频
- 需要文字描述的话要用 Playwright 补充提取

### YouTube

- **主方案**：yt-dlp (最稳定)
- **备选**：Invidious 公共实例 (360p itag=18)
- **注意**：永远不要把带用户 cookie 的 URL 发给第三方代理

---

## 逐字稿统一格式

**为什么要统一格式？**
- 方便后续批量处理（搜索、归档、导入笔记软件）
- 用户体验一致，不用适应不同平台的不同输出
- 便于测试验证

**7 个标准字段（固定顺序）**：
1. 标题
2. 作者
3. 来源 (URL)
4. 平台
5. 语言
6. 时长
7. 生成时间

**时间戳格式**：`[MM:SS - MM:SS]`

> 超过 1 小时的视频暂未验证，可能需要升级到 `[HH:MM:SS - HH:MM:SS]` 格式。

---

## 平台兼容性

### 已验证平台

- **Windows 10/11** — 完整验证
- **macOS** — 理论兼容（pathlib、yt-dlp、whisper 均跨平台），未实测
- **Linux** — 理论兼容，未实测

### 跨平台设计

- 所有路径使用 `pathlib.Path`，自动适配分隔符
- 环境变量检测用 `os.environ.get()`
- 平台特定代码（如 WSL 修复）都用条件判断包起来

### Windows 专属问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| Whisper 导入弹 WSL 窗口 | whisper 检查 WSL 可用性 | `os.environ["WHISPER_NO_WSL"] = "1"` (import 前设置) |
| 后台进程 exit code 1 | WSL 输出污染 stderr | 忽略 exit code，看 CPU 时间 |
| `python -c` 长任务失败 | TUI 输出处理问题 | 写 `.py` 文件执行 |
| Chrome cookie 数据库锁定 | Chrome 运行时锁住 SQLite | 关闭 Chrome，或用浏览器扩展导出 |
| Foreground 600s 硬限制 | Hermes 平台限制 | 长任务用 `background=true` |

### macOS 注意

- Apple Silicon: Whisper 支持 MPS 加速，但 `large-v3-turbo` 可能显存不够
- FFmpeg: `brew install ffmpeg`
- 验证: `ffmpeg -version`

### Linux 注意

- 服务器环境建议设置 `PYTHONUTF8=1`
- NVIDIA GPU 需要装好 CUDA 驱动才能用 GPU 加速
- FFmpeg:
  - Debian/Ubuntu: `sudo apt update && sudo apt install ffmpeg`
  - Fedora/RHEL: `sudo dnf install ffmpeg`
  - Arch: `sudo pacman -S ffmpeg`
- 验证: `ffmpeg -version`

---

## 踩坑记录

### Whisper 相关

1. **`transcribe()` 不接受 Path 对象** → 必须传字符串
   ```python
   model.transcribe(str(path))  # ✅
   model.transcribe(path)       # ❌ TypeError
   ```

2. **小模型输出繁体中文** → 用 `large-v3-turbo` 原生简体输出

3. **长视频幻觉** → 分段转录 + 重复率检测（>50% 相同行 = 幻觉段）

4. **`--vad_filter True` 极慢** → 不要用，分段转录反而更快

### 平台相关

5. **B站 412** → yt-dlp 没用，直接上 API

6. **抖音直连 API 空** → 必须 Playwright 拦截

7. **知乎无头模式被检测** → 必须非无头 + stealth 脚本

8. **小红书 yt-dlp 意外地好用** → 和抖音不同，别搞混

---

## 测试与验证

### 已验证平台（2026-08-03）

| 平台 | 内容类型 | 下载 | 音频提取 | 转录 | 状态 |
|------|---------|------|---------|------|------|
| 微信视频号 | 视频 | ✅ | ✅ | ✅ | 生产可用 |
| B站 | 视频+音频 | ✅ | ✅ | ✅ | 生产可用 |
| 抖音 | 视频 | ✅ | ✅ | ✅ | 生产可用 |
| YouTube | 视频 | ✅ | ✅ | ✅ | 生产可用 |
| X/Twitter | 图文 | ✅ | N/A | N/A | 生产可用 |
| 知乎 | 图文+回答 | ✅ | N/A | N/A | 生产可用 |
| 小红书 | 视频 | ✅ | ✅ | ✅ | 生产可用 |

### 未验证/待改进

- [ ] 超过 1 小时的长视频时间戳格式是否需要 HH:MM:SS
- [ ] 批量任务 20+ 视频的稳定性
- [ ] 小红书图文笔记的高清图提取（目前只能拿到幻灯片视频）
- [ ] 评论提取功能全面验证
- [ ] 各平台登录态 cookie 的标准化处理方式

---

## 扩展指南

### 添加新平台

1. 新建 `Task N: {平台名}` 章节
2. 实现提取函数，返回标准 Record 结构
3. 加到 Platform Method Priority Matrix
4. 加到 Troubleshooting 表里
5. 在 `references/platforms.md` 里加详细实现
6. 写测试脚本跑通验证

### 命名规范

- 函数名：`extract_{平台}()` / `download_{平台}()`
- 记录 kind：小写英文 + 连字符，如 `wx-channels`, `x-twitter-image`
- 记录 platform：首字母大写，如 `WeixinChannels`, `X/Twitter`
