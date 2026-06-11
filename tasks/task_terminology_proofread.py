from ..core.terminology_engine import terminology_engine


def proofread_english_terms(srt_path: str, domain: str = "",
                            glossary_path: str = None,
                            progress_callback=None,
                            log_callback=None):
    """校对英文字幕中的专业术语"""
    return terminology_engine.proofread_english_terms(
        srt_path=srt_path,
        domain=domain,
        glossary_path=glossary_path,
        progress_callback=progress_callback,
        log_callback=log_callback
    )
