import os
from pathlib import Path
from ..core import TTSEngine, config_manager

def convert_srt_to_mp3(srt_path: str, voice: str = None, speed_align: bool = True,
                       max_speed: float = 1.3, progress_callback=None, log_callback=None):
    try:
        srt_path = Path(srt_path)
        
        with open(srt_path, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        
        if log_callback:
            log_callback(f"Converting SRT to MP3: {srt_path.name}")
            log_callback(f"Voice: {voice or 'Default'}, Speed align: {speed_align}, Max speed: {max_speed}")
        
        output_dir = str(config_manager.get_cache_dir() / "tts_temp")
        os.makedirs(output_dir, exist_ok=True)
        
        tts = TTSEngine()
        
        def log_wrapper(message):
            if log_callback:
                log_callback(f"  {message}")
        
        def progress_wrapper(current, total, message):
            if progress_callback:
                progress_callback(current, total, message)
        
        if progress_callback:
            progress_callback(0, 100, "Initializing TTS engine...")
        
        temp_output, new_srt_content = tts.generate_audio_from_srt_strict(
            srt_content,
            voice=voice,
            output_dir=output_dir,
            callback=log_wrapper,
            progress_callback=progress_wrapper,
            max_speed=max_speed,
            speed_align=speed_align
        )
        
        if progress_callback:
            progress_callback(95, 100, "Moving output file...")
        
        # 生成音频文件
        final_output = srt_path.parent / f"{srt_path.stem}.mp3"
        import shutil
        shutil.move(temp_output, str(final_output))
        
        # 不再生成 _synced.srt 文件，因为时间戳会改变导致和视频画面不同步
        # 用户应该使用原始的 SRT 文件（如 _EN.srt）来烧录字幕
        
        if progress_callback:
            progress_callback(100, 100, "Done")
        
        if log_callback:
            log_callback(f"✓ Successfully generated MP3: {final_output.name}")
            log_callback(f"  提示：烧录字幕时请使用原始SRT文件（如 {srt_path.name}）")
        
        return str(final_output)
    
    except Exception as e:
        if log_callback:
            log_callback(f"✗ Failed: {str(e)}")
        raise