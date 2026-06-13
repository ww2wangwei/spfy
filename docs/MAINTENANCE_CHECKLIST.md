# 维护与发布清单

这份清单用于日常修改、测试和打包发布。

## 修改前

- [ ] 运行 `git status --short`，确认已有未提交修改。
- [ ] 不回退用户已有修改。
- [ ] 明确修改范围：GUI、任务层、核心引擎、打包配置或文档。
- [ ] 如果涉及大模型，不要写死模型名，应使用设置中的动态模型。

## 常规开发检查

```powershell
cd F:\视频翻译工具\video_tool
python -m py_compile gui\main_window.py gui\local_correction_window.py core\*.py tasks\*.py main.py
python main.py
```

## 翻译相关检查

- [ ] 第4步翻译后，英文 SRT 不应含中文残留。
- [ ] 英文 SRT 不应含 `<think>`。
- [ ] 英文 SRT 不应含 `I think`、`Let me`、`Given the context`、`Or:`、`chars` 等 AI 思考或候选残留。
- [ ] 所有免费兜底都失败时，只输出 `[Translation Failed]`，不要输出中文原文。

## 英文术语校对检查

- [ ] 输出格式必须类似：`negative side (negative side -> reverse side)`。
- [ ] 不应改写整句。
- [ ] 不应把 AI reason、解释或 JSON 残留写入字幕。
- [ ] 不确定的术语应跳过。
- [ ] 某一批 AI 返回格式异常时，应跳过该批次并继续后续批次。

## 局部修正检查

- [ ] 源视频应选择 `-new.mp4`。
- [ ] 不要选择 `-mute.mp4`。
- [ ] 不要选择 `_final.mp4`。
- [ ] 修改多段字幕后，状态列显示 `已修改`。
- [ ] 批量替换声音后，未修改时间段仍保留原声音。
- [ ] 新字幕不会与旧硬字幕重叠。

## 播放器检查

- [ ] 选择视频后自动播放。
- [ ] 暂停后画面/声音停止。
- [ ] 继续后从暂停位置继续。
- [ ] 拖动进度条能前进/后退。
- [ ] 全屏时右侧小窗口停止，声音只有一份。
- [ ] 全屏控制栏可暂停、继续、拖动进度、恢复窗口。

## Windows 打包

```powershell
cd F:\视频翻译工具\video_tool
python -m PyInstaller --clean -y video_tool.spec
```

检查：

- [ ] `dist\视频翻译工具\视频翻译工具.exe` 可以启动。
- [ ] MP3 -> SRT 不报缺少 `silero_vad_v6.onnx`。
- [ ] 设置面板能保存 API Key 到用户目录。
- [ ] 打包目录未包含你的 API Key。

生成安装程序：

```powershell
& 'D:\Program Files (x86)\Inno Setup 6\ISCC.exe' 'F:\视频翻译工具\video_tool\installer.iss'
```

检查：

- [ ] `dist\视频翻译工具-安装程序.exe` 可安装。
- [ ] 安装后首次启动正常。
- [ ] 安装后设置保存到 `%USERPROFILE%\.video_tool_cache`。

## macOS 打包

GitHub Actions 配置：

```text
.github/workflows/build-macos.yml
```

触发：

- push 到 `main` 且涉及 Python/requirements/spec/workflow。
- 手动 `workflow_dispatch`。

输出：

- `video-tool-macos-dmg`
- `video-tool-macos-app`

## API Key 安全检查

发布前运行：

```powershell
rg "sk-|api_key|MINIMAX_API_KEY|Authorization" -n .
```

人工确认：

- [ ] `core/translator_engine.py` 没有真实 API Key。
- [ ] `model_settings.json` 不在项目目录。
- [ ] `dist` 中不包含个人配置。
- [ ] 安装包不包含缓存目录。

## 常见回归点

- 大模型名称日志应动态显示当前模型。
- 设置面板刷新模型后，主界面模型下拉框同步更新。
- 停止按钮任务开始时可用，任务结束后禁用。
- 第9步生成 `_final.mp4` 后播放器自动指向该文件。
- 打包版和源码版配置路径一致使用用户缓存目录。

## 提交建议

提交前：

```powershell
git status --short
git diff --stat
```

只提交与当前任务相关的文件。不要用 `git reset --hard` 或随意回退用户修改。
