import os
from pathlib import Path
from typing import List
from ..core import FFmpegExecutor, config_manager

def remove_audio_from_mp4(mp4_files: List[str], ffmpeg_path: str = None,
                          progress_callback=None, log_callback=None):
    if ffmpeg_path is None:
        ffmpeg_path = config_manager.get_ffmpeg_path()
    
    ffmpeg = FFmpegExecutor(ffmpeg_path)
    success_count = 0
    fail_count = 0
    
    total_files = len(mp4_files)
    
    for i, mp4_path in enumerate(mp4_files, start=1):
        try:
            mp4_path = Path(mp4_path)
            output_path = mp4_path.parent / f"{mp4_path.stem}-mute.mp4"
            
            if log_callback:
                log_callback(f"[{i}/{total_files}] Removing audio: {mp4_path.name}")
            
            def log_line(line):
                if log_callback:
                    log_callback(f"  {line}")
            
            ffmpeg.remove_audio(str(mp4_path), str(output_path), callback=log_line)
            
            if log_callback:
                log_callback(f"  ✓ Successfully created: {output_path.name}")
            
            success_count += 1
            
        except Exception as e:
            if log_callback:
                log_callback(f"  ✗ Failed: {str(e)}")
            fail_count += 1
        
        if progress_callback:
            progress_callback(i, total_files, f"Processed {i}/{total_files}")
    
    if log_callback:
        log_callback(f"\nAudio removal complete: {success_count} succeeded, {fail_count} failed")
    
    return success_count, fail_count