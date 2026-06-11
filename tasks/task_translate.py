from pathlib import Path
from ..core import TranslatorEngine

def translate_srt(srt_path: str = None, target_lang: str = "en",
                 speed_multiplier: float = 1.0,
                 progress_callback=None, log_callback=None):
    """
    翻译SRT字幕文件
    
    Args:
        srt_path: 字幕文件路径
        target_lang: 目标语言代码（en, ja, ko, fr, de, es, ru等）
        speed_multiplier: 时间轴倍数（1.0=正常，0.9=减慢10%，1.1=加快10%）
        progress_callback: 进度回调
        log_callback: 日志回调
    
    Returns:
        翻译后的SRT文件路径
    """
    try:
        if progress_callback:
            progress_callback(0, 100, "初始化翻译引擎...")
        
        translator = TranslatorEngine()
        
        result = translator.translate_srt(
            srt_path,
            target_lang=target_lang,
            speed_multiplier=speed_multiplier,
            progress_callback=progress_callback,
            log_callback=log_callback
        )
        
        return result
    
    except Exception as e:
        if log_callback:
            log_callback(f"✗ 翻译失败: {str(e)}")
        raise
