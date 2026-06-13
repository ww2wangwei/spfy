# 视频翻译工具

一个基于 Python/Tkinter 的桌面视频处理工具，用于教学视频的音频提取、语音识别、字幕翻译、配音生成、音视频合成、硬字幕烧录、字幕校对、英文术语校对、逐字稿批量翻译和局部修正。

## 快速启动

```powershell
cd F:\视频翻译工具\video_tool
python main.py
```

首次使用语音识别时，`faster-whisper` 会下载模型到用户缓存目录。大模型 API 信息在程序菜单 `工具 -> 设置` 中配置，保存到用户目录，不应写入项目或安装目录。

## 主要功能

主界面功能按钮按工作流排列：

1. `批量 MP4 -> MP3`：从 MP4 提取音频。
2. `MP3 -> 文字(SRT)`：用 Faster Whisper 生成 SRT。
3. `字幕与逐字稿校对`：比较字幕和逐字稿，大意不确定时保守跳过，在错误后用括号标注修正。
4. `中文字幕翻译`：把中文字幕翻译为英文等目标语言，保持原 SRT 时间轴。
5. `英文术语校对`：按专业方向或术语词库检查英文字幕术语。
6. `SRT -> MP3`：用 Edge TTS 从 SRT 生成配音，并按字幕时长对齐。
7. `MP4 去声音`：生成 `-mute.mp4`。
8. `合并音视频(-new)`：把静音视频和配音合并为 `-new.mp4`。
9. `烧录硬字幕(-sub)`：把 SRT 烧录到视频，输出 `_final.mp4`。
10. `批量逐字稿翻译`：把逐字稿文件翻译为中英对照 Word 表格。
11. `局部修正视频`：编辑多个 SRT 段，批量替换这些时间段的配音并重新烧录字幕。

推荐完整流程：

```text
MP4 -> MP3 -> SRT -> 翻译英文SRT -> SRT转MP3 -> MP4去声音 -> 合并音视频(-new) -> 烧录硬字幕(_final)
```

局部修正流程：

```text
无硬字幕源视频(-new.mp4) + 修订SRT -> 批量替换已修改段声音 -> 重新烧录 -> 局部修正版视频
```

## 文档

- [完整项目维护文档](docs/PROJECT_DOCUMENTATION.md)
- [维护与发布清单](docs/MAINTENANCE_CHECKLIST.md)

## 依赖

Windows 基础依赖见 [requirements.txt](requirements.txt)。macOS 打包依赖见 [requirements-macos.txt](requirements-macos.txt)。

外部工具：

- FFmpeg / FFprobe：音视频处理、时长检测、字幕烧录。
- FFplay：主界面右侧播放器内嵌播放使用。
- Inno Setup：生成 Windows 安装程序。

## 打包

Windows 可分发目录：

```powershell
python -m PyInstaller --clean -y video_tool.spec
```

Windows 安装包：

```powershell
& 'D:\Program Files (x86)\Inno Setup 6\ISCC.exe' 'F:\视频翻译工具\video_tool\installer.iss'
```

macOS 通过 GitHub Actions 生成 `.dmg`，配置见 [.github/workflows/build-macos.yml](.github/workflows/build-macos.yml)。

## API Key 安全

大模型 API Key 保存在：

```text
%USERPROFILE%\.video_tool_cache\model_settings.json
```

不要把 API Key 写入源码、spec、安装脚本或仓库根目录。发布安装包前应检查项目目录中没有 `model_settings.json` 或包含密钥的临时文件。
