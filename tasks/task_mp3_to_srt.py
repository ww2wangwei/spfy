import os
from pathlib import Path
from ..core import WhisperEngine, config_manager

def convert_mp3_to_srt(mp3_path: str, language: str = "Chinese", model_name: str = "small",
                       progress_callback=None, log_callback=None, convert_to_simplified: bool = True,
                       lead_time: float = 0.0):
    cache_dir = str(config_manager.get_cache_dir())
    
    try:
        mp3_path = Path(mp3_path)
        output_path = mp3_path.parent / f"{mp3_path.stem}.srt"
        
        if log_callback:
            log_callback(f"Transcribing audio file: {mp3_path.name}")
            log_callback(f"Language: {language}, Model: {model_name}")
            if lead_time > 0:
                log_callback(f"  Using lead time: {lead_time}s")
            if language == "Chinese" and convert_to_simplified:
                log_callback("  繁体中文将自动转换为简体中文")
        
        if progress_callback:
            progress_callback(0, 100, "Loading Whisper model...")
        
        whisper = WhisperEngine(model_name, cache_dir)
        
        def log_wrapper(message):
            if log_callback:
                log_callback(f"  {message}")
        
        if progress_callback:
            progress_callback(20, 100, "Model loaded, starting transcription...")
        
        srt_content = whisper.transcribe(str(mp3_path), language, callback=log_wrapper, 
                                         convert_to_simplified=convert_to_simplified,
                                         lead_time=lead_time)
        
        if progress_callback:
            progress_callback(80, 100, "Transcription complete, saving SRT...")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        if progress_callback:
            progress_callback(100, 100, "Done")
        
        if log_callback:
            log_callback(f"✓ Successfully generated SRT: {output_path.name}")
        
        return str(output_path)
    
    except Exception as e:
        if log_callback:
            log_callback(f"✗ Failed: {str(e)}")
        raise