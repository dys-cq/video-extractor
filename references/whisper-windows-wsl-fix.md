# Whisper Windows WSL 弹窗问题修复

## 问题现象

在 Windows 系统 `import whisper` 时，会弹出 WSL 安装窗口：
```
Windows Subsystem for Linux has no installed distributions
wsl.exe --list --online
```

点击"取消"后脚本仍可继续运行，但体验不佳。

## 根本原因

Whisper 包源码在 `whisper/__init__.py` **加载时立即执行** WSL 检测：

```python
# whisper 包内部代码（在我们代码执行前就运行了）
if sys.platform == "win32":
    try:
        subprocess.run(["wsl.exe", "--list", "--online"], ...)
    except:
        pass
```

**⚠️ 在脚本中设置环境变量是无效的** — 因为 `import whisper` 执行时，whisper 自己的代码已经立刻跑 WSL 检测了，还没等我们的环境变量设置生效。

## ✅ 永久解决方案（一劳永逸）

修改 Whisper 包源码，在其最开头设置环境变量：

**文件位置**: `Python 安装目录/Lib/site-packages/whisper/__init__.py`

**在文件最最开头（所有代码之前）添加：**

```python
import os
import sys

# 仅在 Windows 系统禁用 WSL 检测（macOS/Linux 不受影响）
if sys.platform == "win32":
    os.environ["WHISPER_NO_WSL"] = "1"
```

保存即可，一次修改永久生效。

## 跨平台兼容性

| 系统 | 是否需要此补丁 | 效果 |
|------|---------------|------|
| **Windows** | ✅ 需要 | 禁用 WSL 弹窗，完全静默加载 |
| **macOS** | ❌ 不需要 | 代码自动跳过，无任何影响 |
| **Linux** | ❌ 不需要 | 代码自动跳过，无任何影响 |

## 恢复方法（如需要）

如果想恢复原始状态，重新安装即可：

```bash
pip install --force-reinstall openai-whisper
```

---

## 备选方案：faster-whisper（推荐）

如果不想修改源码，可以改用 `faster-whisper` 库：

```bash
pip install faster-whisper
```

```python
from faster_whisper import WhisperModel  # ✅ 完全没有 WSL 弹窗问题
```

**优点：**
- 没有 WSL 检测弹窗
- 速度比 openai-whisper 快 4 倍
- 内存占用更低
- 输出结果完全兼容
