import os
import time
from typing import Optional, Dict
from faster_whisper import WhisperModel

try:
    from opencc import OpenCC
    OPENCC_AVAILABLE = True
    _converter = OpenCC('t2s')
except ImportError:
    OPENCC_AVAILABLE = False

def traditional_to_simplified(text: str) -> str:
    """将繁体中文转换为简体中文"""
    if OPENCC_AVAILABLE:
        return _converter.convert(text)
    # 如果没有opencc，返回原文（faster-whisper输出通常是简体）
    return text

class WhisperEngine:
    """
    Faster Whisper 引擎 - 使用 CTranslate2 优化的 Whisper 实现

    相比原生 OpenAI Whisper：
    - 速度快 3-5 倍
    - 内存占用更低
    - 支持 FP16/INT8 量化
    """

    def __init__(self, model_name: str = "small", cache_dir: Optional[str] = None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.model = None
        self.language_map = {
            "Chinese": "zh",
            "English": "en",
            "Japanese": "ja",
            "Korean": "ko",
            "French": "fr",
            "German": "de",
            "Spanish": "es",
            "Russian": "ru"
        }

    def load_model(self, callback=None):
        """加载 Faster Whisper 模型"""
        if self.model is None:
            try:
                if callback:
                    callback(f"Loading Faster Whisper {self.model_name} model...")

                # 模型下载路径
                download_root = self.cache_dir if self.cache_dir else None

                # 加载模型 - 使用 medium 精度平衡速度和准确性
                # device="cuda" 使用 GPU, "cpu" 使用 CPU
                # compute_type="float16" 较快速, "int8" 最快但可能有精度损失
                try:
                    # 优先尝试 GPU
                    self.model = WhisperModel(
                        self.model_name,
                        device="cuda",
                        compute_type="float16",
                        download_root=download_root
                    )
                    if callback:
                        callback(f"Faster Whisper {self.model_name} model loaded (GPU/float16)")
                except Exception as gpu_err:
                    # 回退到 CPU
                    if callback:
                        callback(f"GPU not available, using CPU: {str(gpu_err)}")
                    self.model = WhisperModel(
                        self.model_name,
                        device="cpu",
                        compute_type="int8",
                        download_root=download_root
                    )
                    if callback:
                        callback(f"Faster Whisper {self.model_name} model loaded (CPU/int8)")

            except Exception as e:
                if callback:
                    callback(f"Failed to load Faster Whisper model: {str(e)}")
                raise

    def transcribe(self, audio_path: str, language: str = "Chinese", callback=None,
                   convert_to_simplified: bool = True, lead_time: float = 0.0,
                   progress_callback=None) -> str:
        """转录音频为 SRT 字幕"""
        if self.model is None:
            self.load_model(callback)

        lang_code = self.language_map.get(language, "zh")

        try:
            if callback:
                callback(f"Starting transcription with {language}...")

            # 执行转录
            # beam_size=5 提高准确性，best_of=5 多次采样
            segments, info = self.model.transcribe(
                audio_path,
                language=lang_code,
                beam_size=5,
                best_of=5,
                vad_filter=True  # 启用语音活动检测，过滤静音
            )

            if callback:
                callback(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
                if getattr(info, 'duration', None):
                    callback(f"Audio duration: {info.duration:.1f}s")

            # Faster-Whisper 返回的 segment.start/end 已经是原音频时间轴。
            # 不再自动检测首段语音并叠加偏移，否则会把字幕整体推迟。
            time_offset = lead_time if lead_time else 0.0
            if time_offset and callback:
                callback(f"Applying manual timestamp offset: {time_offset:.2f}s...")

            # 生成 SRT 内容
            srt_lines = []
            last_progress_update = 0.0
            for i, segment in enumerate(segments, start=1):
                start_time = segment.start + time_offset
                end_time = segment.end + time_offset
                text = segment.text.strip()

                if progress_callback and getattr(info, 'duration', None):
                    now = time.time()
                    if now - last_progress_update >= 0.5:
                        percent = 20 + min(58, int((segment.end / max(info.duration, 0.1)) * 58))
                        progress_callback(percent, 100, f"正在转写: {segment.end:.1f}/{info.duration:.1f}s")
                        last_progress_update = now
                if callback and (i == 1 or i % 10 == 0):
                    callback(f"Transcribed {i} segments, current time {segment.end:.1f}s")

                # 繁体转简体
                if convert_to_simplified:
                    text = traditional_to_simplified(text)

                # SRT 格式
                srt_lines.append(f"{i}")
                srt_lines.append(f"{self._format_time(start_time)} --> {self._format_time(end_time)}")
                srt_lines.append(text)
                srt_lines.append("")

            if progress_callback:
                progress_callback(78, 100, f"转写完成，共 {len(srt_lines) // 4} 段")

            return '\n'.join(srt_lines)

        except Exception as e:
            if callback:
                callback(f"Transcription failed: {str(e)}")
            raise

    def _detect_first_voice_time(self, audio_path: str) -> float:
        """使用 ffmpeg 检测音频中第一个真正说话的时间"""
        try:
            import subprocess
            import re

            cmd = [
                'ffmpeg', '-i', audio_path,
                '-af', 'silencedetect=noise=-50dB:d=0.2',
                '-f', 'null', '-'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding='utf-8', errors='ignore', timeout=60)

            output = result.stderr if result.stderr else result.stdout
            silence_ends = re.findall(r'silence_end: ([\d.]+)', output)

            if silence_ends:
                first_end = float(silence_ends[0])
                if first_end >= 0.2:
                    return round(first_end, 3)

            return 0.0
        except Exception as e:
            return 0.0

    def _format_time(self, seconds: float) -> str:
        """将秒数格式化为 SRT 时间格式 HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        milliseconds = int((secs - int(secs)) * 1000)
        secs = int(secs)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def get_model_info(self) -> Dict:
        """获取模型信息"""
        return {
            "name": self.model_name,
            "type": "faster-whisper",
            "language_map": self.language_map
        }
