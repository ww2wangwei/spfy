from ..core.transcript_translate_engine import transcript_translate_engine


def translate_transcript_files(file_paths, progress_callback=None, log_callback=None):
    """批量翻译逐字稿 Word/TXT 文件并输出三列表格 Word"""
    return transcript_translate_engine.translate_files(
        file_paths=file_paths,
        progress_callback=progress_callback,
        log_callback=log_callback
    )
