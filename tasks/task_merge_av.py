import os
from pathlib import Path
from typing import List, Tuple
from ..core import FFmpegExecutor, config_manager

def merge_audio_video(video_file: str, audio_file: str, ffmpeg_path: str = None,
                      progress_callback=None, log_callback=None):
    """
    合并单个视频文件和音频文件
    
    Args:
        video_file: 视频文件路径
        audio_file: 音频文件路径
        ffmpeg_path: FFmpeg路径
        progress_callback: 进度回调
        log_callback: 日志回调
    
    Returns:
        (success_count, fail_count)
    """
    if ffmpeg_path is None:
        ffmpeg_path = config_manager.get_ffmpeg_path()
    
    ffmpeg = FFmpegExecutor(ffmpeg_path)
    
    video_path = Path(video_file)
    audio_path = Path(audio_file)
    
    if not video_path.exists():
        if log_callback:
            log_callback(f"✗ 视频文件不存在: {video_file}")
        return 0, 1
    
    if not audio_path.exists():
        if log_callback:
            log_callback(f"✗ 音频文件不存在: {audio_file}")
        return 0, 1
    
    if log_callback:
        log_callback(f"开始合并音视频...")
        log_callback(f"  视频文件: {video_path.name}")
        log_callback(f"  音频文件: {audio_path.name}")
    
    if progress_callback:
        progress_callback(10, 100, "准备合并...")
    
    try:
        # 生成输出文件名
        base_name = video_path.stem
        # 移除可能存在的 -mute 后缀
        if base_name.endswith('-mute'):
            base_name = base_name[:-5]
        
        output_path = video_path.parent / f"{base_name}-new.mp4"
        
        # 检查路径长度
        output_path_str = str(output_path)
        if len(output_path_str) > 250:
            # 路径过长，使用短路径或临时目录
            import tempfile
            temp_dir = tempfile.gettempdir()
            output_path = Path(temp_dir) / f"{base_name[:30]}-new.mp4"
            if log_callback:
                log_callback(f"  警告：原路径过长，使用临时目录: {output_path}")
        
        if log_callback:
            log_callback(f"  输出文件: {output_path.name}")
        
        if progress_callback:
            progress_callback(20, 100, "执行合并...")
        
        def log_line(line):
            if log_callback:
                log_callback(f"    {line}")
        
        ffmpeg.merge_audio_video(str(video_path), str(audio_path), str(output_path), callback=log_line)
        
        # 如果使用了临时目录，复制回原目录
        if output_path.parent != video_path.parent:
            import shutil
            final_output = video_path.parent / f"{base_name}-new.mp4"
            shutil.move(str(output_path), str(final_output))
            output_path = final_output
        
        if progress_callback:
            progress_callback(90, 100, "合并完成...")
        
        if log_callback:
            log_callback(f"  ✓ 成功创建: {output_path.name}")
        
        if progress_callback:
            progress_callback(100, 100, "完成")
        
        return 1, 0
        
    except Exception as e:
        if log_callback:
            log_callback(f"  ✗ 合并失败: {str(e)}")
        return 0, 1