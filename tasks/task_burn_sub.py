import os
from pathlib import Path
from typing import List, Tuple
from ..core import FFmpegExecutor, config_manager

def burn_subtitle(video_file: str, srt_file: str, use_hardware_accel: bool = False,
                  ffmpeg_path: str = None, progress_callback=None, log_callback=None):
    """
    将字幕烧录到视频中
    
    Args:
        video_file: 视频文件路径
        srt_file: 字幕文件路径
        use_hardware_accel: 是否使用硬件加速
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
    srt_path = Path(srt_file)
    
    if not video_path.exists():
        if log_callback:
            log_callback(f"✗ 视频文件不存在: {video_file}")
        return 0, 1
    
    if not srt_path.exists():
        if log_callback:
            log_callback(f"✗ 字幕文件不存在: {srt_file}")
        return 0, 1
    
    if log_callback:
        log_callback(f"开始烧录字幕...")
        log_callback(f"  视频文件: {video_path.name}")
        log_callback(f"  字幕文件: {srt_path.name}")
        if use_hardware_accel:
            log_callback(f"  使用硬件加速")
    
    if progress_callback:
        progress_callback(10, 100, "准备烧录...")
    
    try:
        # 生成输出文件名
        base_name = video_path.stem
        # 移除可能存在的 -new 后缀
        if base_name.endswith('-new'):
            base_name = base_name[:-4]
        
        output_path = video_path.parent / f"{base_name}_final.mp4"
        
        if log_callback:
            log_callback(f"  输出文件: {output_path.name}")
        
        if progress_callback:
            progress_callback(20, 100, "执行烧录...")
        
        def log_line(line):
            if log_callback:
                log_callback(f"    {line}")
        
        ffmpeg.burn_subtitle(str(video_path), str(srt_path), str(output_path),
                             use_hardware_accel=use_hardware_accel, callback=log_line)
        
        if progress_callback:
            progress_callback(90, 100, "烧录完成...")
        
        if log_callback:
            log_callback(f"  ✓ 成功创建: {output_path.name}")
        
        if progress_callback:
            progress_callback(100, 100, "完成")
        
        return 1, 0
        
    except Exception as e:
        if log_callback:
            log_callback(f"  ✗ 烧录失败: {str(e)}")
        return 0, 1