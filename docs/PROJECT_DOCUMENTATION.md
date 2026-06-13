# 视频翻译工具项目维护文档

本文档面向后续维护者，说明项目目标、运行方式、模块结构、核心流程、配置位置、打包发布和常见故障。

## 1. 项目概览

视频翻译工具是一个 Python/Tkinter 桌面应用，主要服务于教学视频的字幕与配音生产流程。它把多个独立能力串成一个桌面工作台：

- 使用 FFmpeg 提取、静音、合并、烧录视频。
- 使用 Faster Whisper 从音频识别 SRT。
- 使用大模型和免费兜底接口翻译中文字幕。
- 使用 Edge TTS 从 SRT 生成配音。
- 使用大模型校对字幕与逐字稿、英文专业术语。
- 使用 Word/TXT/SRT 等逐字稿输入批量生成中英对照 Word。
- 对已生成视频进行局部字幕和局部配音修正。
- 在主窗口右侧内嵌 FFplay 播放器预览最终视频。

项目入口是 [main.py](../main.py)，主窗口是 [gui/main_window.py](../gui/main_window.py)。

## 2. 目录结构

```text
video_tool/
  main.py                         程序入口，创建 Tk 根窗口并加载 MainWindow
  core/                           核心能力层
    config.py                     用户配置、缓存目录、FFmpeg 路径
    ffmpeg_executor.py            FFmpeg/FFprobe 封装
    whisper_engine.py             Faster Whisper 识别
    tts_engine.py                 Edge TTS 配音和 SRT 时间轴对齐
    translator_engine.py          中文字幕翻译、大模型调用、兜底翻译、清理 AI 残留
    proofread_engine.py           字幕与逐字稿 AI 校对
    terminology_engine.py         英文术语校对
    transcript_translate_engine.py 批量逐字稿翻译为 Word 表格
    srt_parser.py                 SRT 解析与写入
    task_manager.py               任务忙闲状态和停止请求
    file_matcher.py               文件匹配辅助
  tasks/                          UI 调用的任务函数层
  gui/                            Tkinter 界面层
    main_window.py                主界面、功能按钮、播放器、任务调度
    settings_window.py            大模型设置窗口
    local_correction_window.py    局部修正窗口
  utils/                          日志、文件大小、打开目录等工具
  video_tool.spec                 Windows PyInstaller 配置
  video_tool_macos.spec           macOS PyInstaller 配置
  installer.iss                   Inno Setup 安装包配置
  .github/workflows/build-macos.yml macOS 自动打包工作流
```

## 3. 启动和运行

开发环境启动：

```powershell
cd F:\视频翻译工具\video_tool
python main.py
```

入口逻辑：

1. [main.py](../main.py) 把项目父目录加入 `sys.path`，确保 `video_tool` 包可导入。
2. 创建 `tk.Tk()`。
3. 创建 `MainWindow`。
4. 设置关闭回调 `app.on_closing`。
5. 进入 `root.mainloop()`。

主窗口启动后会：

- 加载大模型设置。
- 初始化 TTS 声音列表。
- 启动 `task_manager`。
- 设置日志和进度回调。
- 启动队列轮询，用于从后台线程安全更新 Tk UI。

## 4. 配置和缓存

配置管理在 [core/config.py](../core/config.py)。

默认用户缓存目录：

```text
%USERPROFILE%\.video_tool_cache
```

主要文件：

```text
%USERPROFILE%\.video_tool_cache\config.json
%USERPROFILE%\.video_tool_cache\model_settings.json
```

`config.json` 存储通用配置：

- `ffmpeg_path`
- `cache_dir`
- `default_language`
- `default_model`
- `default_voice`
- `speed_align`
- `max_speed`
- `burn_acceleration`
- `log_level`

`model_settings.json` 存储大模型配置：

- `api_key`
- `api_url`
- `models`
- `current_model`

维护注意：

- 安装目录可能不可写，所以模型设置必须保存在用户缓存目录。
- 不要把 API Key 写入项目文件。
- 打包前检查项目目录中是否误留 `model_settings.json`。

## 5. 主界面和任务调度

主界面在 [gui/main_window.py](../gui/main_window.py)。

### UI 分区

- 参数配置区：语言、识别模型、TTS 人声、翻译目标、翻译模型、语速对齐、硬件编码。
- 功能区：11 个主功能按钮。
- 视频播放器：右侧内嵌 FFplay 预览区，支持自动播放、暂停、继续、进度拖动、全屏、恢复窗口。
- 进度条区：显示当前任务进度和停止按钮。
- 日志区：后台任务输出日志。

### 后台线程

长任务通过 `threading.Thread(..., daemon=True)` 执行。后台线程不能直接更新 Tk 控件，而是调用：

- `add_log(message)` 把日志写入队列。
- `update_progress(current, total, message)` 把进度写入队列。
- `process_download_queue()` 在主线程轮询队列并更新 UI。

### 忙闲状态

主窗口在任务开始时调用 `_start_task()`，结束时调用 `_reset_progress_safe()`。部分任务会先检查 `task_manager.is_busy()`，防止并发执行。

## 6. 功能工作流

### 6.1 批量 MP4 -> MP3

入口：`MainWindow.do_mp4_to_mp3()`  
任务：[tasks/task_mp4_to_mp3.py](../tasks/task_mp4_to_mp3.py)  
核心：[core/ffmpeg_executor.py](../core/ffmpeg_executor.py)

输出命名：

```text
输入:  demo.mp4
输出:  demo.mp3
```

FFmpeg 参数核心：

```text
-i input.mp4 -vn -acodec libmp3lame -b:a 192k -ar 44100 output.mp3
```

### 6.2 MP3 -> 文字(SRT)

入口：`MainWindow.do_mp3_to_srt()`  
任务：[tasks/task_mp3_to_srt.py](../tasks/task_mp3_to_srt.py)  
核心：[core/whisper_engine.py](../core/whisper_engine.py)

输出命名：

```text
输入:  demo.mp3
输出:  demo.srt
```

识别行为：

- 使用 `faster-whisper`。
- 优先尝试 GPU `cuda/float16`，失败后回退 CPU `int8`。
- `vad_filter=True` 过滤静音。
- 不自动叠加首段语音偏移，避免字幕整体推迟。
- 可手动输入 `lead_time` 进行时间轴偏移。
- 中文识别可将繁体转简体；依赖 `opencc`，没有时保留原文。

常见问题：

- 打包版缺少 `silero_vad_v6.onnx` 时，检查 spec 是否包含：

```python
datas += collect_data_files('faster_whisper', includes=['assets/*'])
```

### 6.3 中文字幕翻译

入口：`MainWindow.do_translate()`  
核心：[core/translator_engine.py](../core/translator_engine.py)

当前主要使用 `translate_srt_strict_netflix()`，设计目标是：

- 中文 SRT 与英文 SRT 1:1 对应。
- 时间轴完全不改。
- 英文每行不超过约 42 字符。
- 最多两行。
- 清理 AI 思考、候选翻译、字符统计和中文残留。

大模型配置来自设置面板，不应写死模型。

失败兜底链：

```text
主大模型重试 -> Google -> MyMemory -> LibreTranslate -> Argos离线(可选) -> [Translation Failed]
```

如果所有兜底失败，输出 `[Translation Failed]`，不再把中文原文写入英文字幕。

维护重点：

- `strip_reasoning_artifacts()` 是清理 AI 残留的核心函数。
- `looks_like_reasoning()` 判断模型输出是否像思考过程。
- `has_chinese_residue()` 防止英文字幕残留中文。
- 新模型如果容易输出 `<think>`、`Or:`、`chars`、候选翻译，应优先加强这些函数。

### 6.4 英文术语校对

入口：`MainWindow.do_terminology_proofread()`  
任务：[tasks/task_terminology_proofread.py](../tasks/task_terminology_proofread.py)  
核心：[core/terminology_engine.py](../core/terminology_engine.py)

输入：

- 英文 SRT。
- 专业方向，例如 `电气制图`。
- 可选术语词库：`.txt`、`.csv`、`.docx`。

输出：

```text
xxx_术语校对版.srt
xxx_术语校对报告.txt
```

标注格式：

```text
The negative side (negative side -> reverse side)
```

设计原则：

- 只校对专业术语。
- 不改普通语法、风格和句式。
- 不确定就跳过。
- AI 返回解析只取第一个有效 JSON。
- 某批次格式异常时跳过该批次，不中断整个任务。
- 术语建议如果包含解释、长句、思考残留或 `->`，会被拒绝。

### 6.5 字幕与逐字稿校对

入口：`MainWindow.do_proofread()`  
任务：[tasks/task_proofread_correction.py](../tasks/task_proofread_correction.py)  
核心：[core/proofread_engine.py](../core/proofread_engine.py)

目标：

- 比较字幕和逐字稿大意。
- 找出字幕中不准确的地方。
- 在错误内容后用括号标注修正。

示例：

```text
文字符号是用于电器技术领域中技术文件的编织（编织→编制）
```

用户偏好：

- 更看重准确性。
- 宁可不改，保守跳过。

维护重点：

- 如果大模型超时，应考虑增大超时、降低批次大小或增强重试。
- 输出不要覆盖原始 SRT。

### 6.6 SRT -> MP3

入口：`MainWindow.do_srt_to_mp3()`  
任务：[tasks/task_srt_to_mp3.py](../tasks/task_srt_to_mp3.py)  
核心：[core/tts_engine.py](../core/tts_engine.py)

输出命名：

```text
输入:  demo_EN.srt
输出:  demo_EN.mp3
```

行为：

- 使用 Edge TTS。
- 每段生成临时音频。
- 根据 SRT 时间戳严格对齐。
- 音频过短时补静音。
- 音频过长时按 `max_speed` 加速或截断。
- 不生成新的 `_synced.srt`，烧录时仍应使用原 SRT。

### 6.7 MP4 去声音

入口：`MainWindow.do_mute_video()`  
任务：[tasks/task_mute_video.py](../tasks/task_mute_video.py)

输出命名：

```text
输入:  demo.mp4
输出:  demo-mute.mp4
```

用途：

- 为后续重新配音准备无声视频。

注意：

- `-mute.mp4` 没有原音轨，不适合局部修正视频的源视频。

### 6.8 合并音视频(-new)

入口：`MainWindow.do_merge_av()`  
任务：[tasks/task_merge_av.py](../tasks/task_merge_av.py)

输出命名：

```text
输入:  demo-mute.mp4 + demo_EN.mp3
输出:  demo-new.mp4
```

`-new.mp4` 是“无硬字幕但有新配音”的视频。局部修正应优先选择它作为源视频。

### 6.9 烧录硬字幕

入口：`MainWindow.do_burn_sub()`  
任务：[tasks/task_burn_sub.py](../tasks/task_burn_sub.py)

输出命名：

```text
输入:  demo-new.mp4 + demo_EN.srt
输出:  demo_final.mp4
```

烧录完成后，主窗口右侧播放器会自动设置为 `_final.mp4`，并按勾选项自动播放。

注意：

- `_final.mp4` 已有硬字幕，不适合作为局部修正源视频，否则会新旧字幕重叠。
- 硬字幕已经变成画面像素，程序不能可靠清除。

### 6.10 批量逐字稿翻译

入口：`MainWindow.do_transcript_translate()`  
任务：[tasks/task_transcript_translate.py](../tasks/task_transcript_translate.py)  
核心：[core/transcript_translate_engine.py](../core/transcript_translate_engine.py)

支持输入：

```text
.doc
.docx
.txt
.md
.srt
.csv
```

目标输出：

- Word 表格结构。
- 通常用于将中文自然段翻译为英文，并保留对照关系。

### 6.11 局部修正视频

入口：`MainWindow.do_local_correction()`  
窗口：[gui/local_correction_window.py](../gui/local_correction_window.py)

使用场景：

- 最终视频发现少数字幕或配音错误。
- 不想重跑完整流程。

正确输入：

```text
源视频: xxx-new.mp4
字幕:   对应 SRT
```

不要选择：

- `xxx-mute.mp4`：没有原声音轨。
- `xxx_final.mp4`：已有硬字幕，会重叠。

功能：

- 加载 SRT。
- 按段号、时间、内容搜索。
- 修改多个字幕段。
- 自动标记已修改段。
- 批量生成修改段配音。
- 对源视频对应时间段静音。
- 把新配音覆盖到对应时间点。
- 用完整修订 SRT 重新烧录。

音频替换逻辑：

```text
完整原音轨
  -> 只静音已修改时间段
  -> 在同一时间点叠加新 TTS 音频
  -> 保留其他位置声音
```

## 7. 视频播放器

播放器在 [gui/main_window.py](../gui/main_window.py)。

实现方式：

- 使用 `ffplay` 播放视频。
- Windows 下通过 `pywin32` 把 FFplay 窗口嵌入 Tk Frame。
- 支持选择视频后自动播放。
- 支持暂停、继续、拖动进度条、全屏、恢复窗口。
- 进度条通过程序记录起始时间和偏移时间维护。
- 拖动进度条时会从目标时间重新启动播放。

限制：

- 依赖系统能找到 `ffplay`。
- 如果嵌入失败，可能退回独立窗口或系统播放器。
- 暂停实现为记录当前进度并停止进程；继续时从该进度重新播放。

## 8. 大模型设置

设置窗口在 [gui/settings_window.py](../gui/settings_window.py)。

功能：

- 填写 API Key。
- 填写 API 地址。
- 点击“刷新模型”从 `/models` 获取模型列表。
- 添加、更新、删除模型。
- 设为默认模型。
- 保存并立即应用。

配置保存位置：

```text
%USERPROFILE%\.video_tool_cache\model_settings.json
```

运行时通过：

```python
update_translation_config(api_key, api_url, models, current_model)
```

更新全局翻译配置。

## 9. 打包发布

### 9.1 Windows PyInstaller

配置：[video_tool.spec](../video_tool.spec)

命令：

```powershell
python -m PyInstaller --clean -y video_tool.spec
```

输出：

```text
dist\视频翻译工具\视频翻译工具.exe
```

关键配置：

- `pathex=['F:\\视频翻译工具']`
- `collect_submodules('edge_tts')`
- `collect_submodules('win32com')`
- `collect_submodules('pythoncom')`
- `collect_submodules('pysrt')`
- `collect_data_files('faster_whisper', includes=['assets/*'])`

`faster_whisper/assets/*` 必须包含，否则打包版 MP3 转 SRT 可能报缺少 `silero_vad_v6.onnx`。

### 9.2 Windows 安装程序

配置：[installer.iss](../installer.iss)

命令：

```powershell
& 'D:\Program Files (x86)\Inno Setup 6\ISCC.exe' 'F:\视频翻译工具\video_tool\installer.iss'
```

输出：

```text
dist\视频翻译工具-安装程序.exe
```

安装包会打包：

```text
dist\视频翻译工具\*
```

### 9.3 macOS 打包

配置：

- [requirements-macos.txt](../requirements-macos.txt)
- [video_tool_macos.spec](../video_tool_macos.spec)
- [.github/workflows/build-macos.yml](../.github/workflows/build-macos.yml)

GitHub Actions 会：

1. 使用 macOS 14。
2. 安装 Python 3.11。
3. 安装 `ffmpeg` 和 `create-dmg`。
4. 安装 `requirements-macos.txt`。
5. 使用 PyInstaller 生成 `.app`。
6. 使用 `create-dmg` 生成 DMG。
7. 上传 DMG 和 app bundle artifact。

## 10. 安全和发布前检查

发布前必须确认：

- 项目目录没有 API Key。
- 安装包没有打入 `model_settings.json`。
- `dist` 中没有个人缓存文件。
- `.gitignore` 覆盖常见构建产物和缓存。
- 打包后首次运行仍能在用户目录保存设置。

常见敏感文件：

```text
model_settings.json
*.key
*.env
%USERPROFILE%\.video_tool_cache\model_settings.json
```

## 11. 常见故障

### 11.1 打包版 Whisper 缺少 silero_vad_v6.onnx

现象：

```text
faster_whisper\assets\silero_vad_v6.onnx failed. File doesn't exist
```

处理：

- 检查 spec 中是否包含 `collect_data_files('faster_whisper', includes=['assets/*'])`。
- 重新 `PyInstaller --clean`。

### 11.2 大模型 401

现象：

```text
authorized_error
Please carry the API secret key in the Authorization field
```

处理：

- 打开 `工具 -> 设置`。
- 填写正确 API Key 和 API 地址。
- 点击刷新模型。
- 保存并应用。

### 11.3 大模型 502 或超时

处理：

- 程序已有重试。
- 可换模型。
- 翻译功能会走免费兜底链。
- 校对功能建议减小批次大小或稍后重试。

### 11.4 翻译结果混入 AI 思考

维护位置：

- [core/translator_engine.py](../core/translator_engine.py)
- `strip_reasoning_artifacts()`
- `looks_like_reasoning()`

新增模型后，如果出现新的残留模式，应优先在这里加清理规则。

### 11.5 英文术语校对 Extra data

现象：

```text
Extra data: line xx column xx
```

原因：

- AI 返回多个 JSON。
- JSON 后有解释文字。

处理位置：

- [core/terminology_engine.py](../core/terminology_engine.py)
- `_extract_first_json_object()`

### 11.6 局部修正声音重叠

原因：

- 选了 `_final.mp4`，旧硬字幕无法清除。
- 选了 `-mute.mp4`，没有原音轨。

正确做法：

- 选择 `-new.mp4` 作为源视频。

## 12. 维护建议

### 修改功能按钮

位置：

- [gui/main_window.py](../gui/main_window.py)
- `btn_specs`
- `cmd_map`

注意：

- 用户要求按钮编号按视觉位置顺序排列。
- 新增按钮后同步更新帮助文本。

### 修改翻译模型

不要在功能代码中写死模型。应通过：

```python
translator_engine.get_translation_model()
translator_engine.TRANSLATION_MODELS
```

从设置读取。

### 修改输出文件名

任务层负责输出命名。常见规则：

```text
.mp4 -> .mp3
.mp3 -> .srt
.srt -> .mp3
.mp4 -> -mute.mp4
-mute.mp4 + .mp3 -> -new.mp4
-new.mp4 + .srt -> _final.mp4
英文术语校对 -> _术语校对版.srt
```

改命名时应同步文档、日志和用户提示。

### 添加新依赖

同时更新：

- [requirements.txt](../requirements.txt)
- [requirements-macos.txt](../requirements-macos.txt)
- `video_tool.spec` hiddenimports/datas
- `video_tool_macos.spec` hiddenimports/datas
- 打包文档

## 13. 质量检查

常用检查命令：

```powershell
python -m py_compile gui\main_window.py gui\local_correction_window.py core\*.py tasks\*.py main.py
```

启动程序：

```powershell
python main.py
```

打包检查：

```powershell
python -m PyInstaller --clean -y video_tool.spec
```

测试重点：

- 设置面板刷新模型并保存。
- 第4步翻译是否无中文残留、无 AI 思考残留。
- 第5步英文术语校对是否只产生 `wrong (wrong -> correct)`。
- 第9步烧录后播放器是否自动设置并播放 `_final.mp4`。
- 局部修正是否使用 `-new.mp4`，多段替换声音是否保留其他原音。

## 14. 概念图

```text
GUI(MainWindow)
  |
  |-- tasks/*.py 负责单个用户动作
        |
        |-- core/ffmpeg_executor.py       音视频处理
        |-- core/whisper_engine.py        MP3 -> SRT
        |-- core/tts_engine.py            SRT -> MP3
        |-- core/translator_engine.py     中文字幕翻译
        |-- core/proofread_engine.py      字幕/逐字稿校对
        |-- core/terminology_engine.py    英文术语校对
        |-- core/transcript_translate_engine.py 逐字稿翻译
```

视频生产流程：

```text
原视频.mp4
  |-- MP4 -> MP3 --------------------> 原音频.mp3
  |                                      |
  |                                      v
  |                                  Whisper
  |                                      |
  |                                      v
  |                                  中文字幕.srt
  |                                      |
  |                                      v
  |                                  英文字幕.srt
  |                                      |
  |                                      v
  |                                  TTS配音.mp3
  |
  |-- 去声音 -> 原视频-mute.mp4 --------+
                                         |
                                         v
                                  合并 -> 原视频-new.mp4
                                         |
                                         v
                                  烧录 -> 原视频_final.mp4
```
