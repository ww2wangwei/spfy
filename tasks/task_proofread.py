import os
from pathlib import Path
from ..core import ProofreadEngine

def proofread_srt(srt_path: str = None, transcript_path: str = None,
                  progress_callback=None, log_callback=None):
    """
    校对字幕与逐字稿
    
    Args:
        srt_path: 字幕文件路径（如果为None，会弹出文件选择对话框）
        transcript_path: 逐字稿路径（如果为None，会弹出文件选择对话框）
        progress_callback: 进度回调
        log_callback: 日志回调
    """
    try:
        proofread = ProofreadEngine()
        
        if progress_callback:
            progress_callback(10, 100, "准备校对...")
        
        # 加载文件
        srt_segments = proofread.load_srt(srt_path)
        transcript = proofread.load_txt(transcript_path)
        
        if log_callback:
            log_callback(f"加载完成: {len(srt_segments)} 个字幕段")
        
        if progress_callback:
            progress_callback(30, 100, "正在对比文本...")
        
        # 提取字幕文本
        subtitle_text = proofread.extract_text_from_srt(srt_segments)
        
        # 获取逐字稿行和字幕行
        subtitle_lines = subtitle_text.split('\n')
        transcript_lines = transcript.split('\n')
        
        if progress_callback:
            progress_callback(60, 100, "正在计算差异...")
        
        # 计算统计
        import difflib
        matcher = difflib.SequenceMatcher(None, transcript_lines, subtitle_lines)
        
        stats = {
            'transcript_lines': len(transcript_lines),
            'subtitle_lines': len(subtitle_lines),
            'similarity': matcher.ratio() * 100
        }
        
        if progress_callback:
            progress_callback(80, 100, "正在生成报告...")
        
        # 生成对比结果
        diff_result = list(difflib.unified_diff(
            transcript_lines,
            subtitle_lines,
            fromfile='逐字稿',
            tofile='字幕',
            lineterm=''
        ))
        
        # 生成报告
        report = proofread._generate_report(
            srt_path, transcript_path,
            srt_segments, transcript,
            subtitle_lines, transcript_lines,
            diff_result, stats
        )
        
        # 保存报告
        report_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_校对报告.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        if progress_callback:
            progress_callback(100, 100, "校对完成")
        
        if log_callback:
            log_callback(f"✓ 校对完成")
            log_callback(f"  逐字稿行数: {stats['transcript_lines']}")
            log_callback(f"  字幕行数: {stats['subtitle_lines']}")
            log_callback(f"  相似度: {stats['similarity']:.2f}%")
            log_callback(f"  报告已保存: {report_path}")
        
        return report_path, stats
    
    except Exception as e:
        if log_callback:
            log_callback(f"✗ 校对失败: {str(e)}")
        raise
