from pathlib import Path
from ..core.proofread_engine import proofread_engine

def proofread_and_correct_srt(srt_path: str, transcript_path: str,
                              progress_callback=None, log_callback=None):
    """
    校对字幕并在字幕后用括号标注正确内容

    Args:
        srt_path: 字幕文件路径
        transcript_path: 逐字稿文件路径
        progress_callback: 进度回调 (current, total, message)
        log_callback: 日志回调

    Returns:
        Tuple[修正字幕路径, 校对报告路径, 统计信息]
    """
    return proofread_engine.proofread_with_ai(
        srt_path=srt_path,
        transcript_path=transcript_path,
        progress_callback=progress_callback,
        log_callback=log_callback
    )