import subprocess
import os
import shlex
from typing import List, Optional

class FFmpegExecutor:
    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path

    def _subprocess_kwargs(self) -> dict:
        """Hide FFmpeg console windows when this app runs as a Windows GUI."""
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NO_WINDOW}
        return {}
    
    def run_command(self, args: List[str], callback=None) -> str:
        full_cmd = [self.ffmpeg_path] + args
        try:
            if callback:
                process = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    **self._subprocess_kwargs()
                )
                output_lines = []
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        output_lines.append(line.strip())
                        if callback:
                            callback(line.strip())
                return_code = process.wait()
                if return_code != 0:
                    raise Exception(f"FFmpeg command failed with code {return_code}: {''.join(output_lines)}")
                return '\n'.join(output_lines)
            else:
                result = subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    **self._subprocess_kwargs()
                )
                if result.returncode != 0:
                    raise Exception(f"FFmpeg command failed: {result.stderr}")
                return result.stdout
        except FileNotFoundError:
            raise Exception(f"FFmpeg not found at {self.ffmpeg_path}. Please install FFmpeg or set the correct path.")
        except OSError as e:
            # 处理路径相关的错误
            if "Invalid argument" in str(e):
                raise Exception(f"FFmpeg无法打开输出文件，可能是路径过长或包含特殊字符: {str(e)}")
            raise
        except Exception as e:
            raise Exception(f"FFmpeg execution error: {str(e)}")
    
    def extract_audio(self, input_path: str, output_path: str, callback=None) -> str:
        args = [
            '-i', input_path,
            '-vn',
            '-acodec', 'libmp3lame',
            '-b:a', '192k',
            '-ar', '44100',
            '-y',
            output_path
        ]
        return self.run_command(args, callback)
    
    def remove_audio(self, input_path: str, output_path: str, callback=None) -> str:
        args = [
            '-i', input_path,
            '-c:v', 'copy',
            '-an',
            '-y',
            output_path
        ]
        return self.run_command(args, callback)
    
    def merge_audio_video(self, video_path: str, audio_path: str, output_path: str, callback=None) -> str:
        # 获取视频和音频的时长
        video_duration = self.get_video_duration(video_path)
        audio_duration = self.get_audio_duration(audio_path)
        
        args = [
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ar', '48000',
            '-y',
            output_path
        ]
        
        # 如果音频比视频长，截断音频到视频长度
        if audio_duration > video_duration and video_duration > 0:
            # 添加音频截断参数（使用atrim，不是trim）
            args.insert(-1, '-af')
            args.insert(-1, f'atrim=duration={video_duration}')
        elif video_duration > audio_duration and audio_duration > 0:
            # 如果视频比音频长，让视频适应音频长度
            args.insert(-1, '-shortest')
        
        return self.run_command(args, callback)
    
    def get_video_duration(self, video_path: str) -> float:
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                **self._subprocess_kwargs()
            )
            import json
            info = json.loads(result.stdout)
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    return float(stream.get('duration', 0))
        except:
            pass
        return 0.0
    
    def burn_subtitle(self, video_path: str, subtitle_path: str, output_path: str, 
                      use_hardware_accel: bool = False, callback=None) -> str:
        # 处理Windows路径中的冒号问题
        # FFmpeg的subtitles滤镜会把冒号当作选项分隔符，需要特殊处理
        escaped_subtitle_path = self._escape_ffmpeg_path(subtitle_path)
        
        args = [
            '-i', video_path,
            '-vf', f"subtitles={escaped_subtitle_path}",
            '-y'
        ]
        
        if use_hardware_accel:
            encoder = self._detect_hardware_encoder()
            if encoder:
                args.insert(-1, '-c:v')
                args.insert(-1, encoder)
            else:
                args.insert(-1, '-c:v')
                args.insert(-1, 'libx264')
        else:
            args.insert(-1, '-c:v')
            args.insert(-1, 'libx264')
        
        args.append(output_path)
        return self.run_command(args, callback)
    
    def _escape_ffmpeg_path(self, path: str) -> str:
        """
        转义FFmpeg滤镜参数中的路径，处理Windows路径问题
        FFmpeg滤镜参数中，冒号是选项分隔符，需要特殊处理
        """
        # 将反斜杠转换为正斜杠
        path = path.replace('\\', '/')
        
        # Windows盘符处理：将 F:/path 转义为 F\\:/path
        # 这样可以避免冒号被当作选项分隔符
        if len(path) >= 2 and path[1] == ':':
            # 对盘符冒号进行转义：F:/ -> F\\:/
            return path[:1] + '\\\\:' + path[2:]
        return path
    
    def _detect_hardware_encoder(self) -> Optional[str]:
        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-encoders'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                **self._subprocess_kwargs()
            )
            encoders = result.stdout
            if 'h264_nvenc' in encoders:
                return 'h264_nvenc'
            elif 'h264_qsv' in encoders:
                return 'h264_qsv'
            elif 'h264_amf' in encoders:
                return 'h264_amf'
        except:
            pass
        return None
    
    def get_audio_duration(self, audio_path: str) -> float:
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', audio_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                **self._subprocess_kwargs()
            )
            import json
            info = json.loads(result.stdout)
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    return float(stream.get('duration', 0))
        except:
            pass
        return 0.0
    
    def speed_audio(self, input_path: str, output_path: str, speed: float, callback=None) -> str:
        args = [
            '-i', input_path,
            '-filter:a', f'atempo={speed}',
            '-y',
            output_path
        ]
        return self.run_command(args, callback)
