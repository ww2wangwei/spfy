import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Tuple, Dict, Any
import difflib
import time
import importlib

translator_engine = importlib.import_module('video_tool.core.translator_engine')

class ProofreadEngine:
    """字幕与逐字稿校对引擎"""
    
    def __init__(self):
        self.ai_proofread_batch_size = 15
        self.proofread_term_fixes = {
            "机电器": "继电器",
            "十度": "识读",
            "静密": "精密",
            "起电器": "其电气",
            "喘动": "传动",
            "领散": "零散",
            "试图": "识图",
            "抛息": "剖析",
            "剧情": "矩形",
            "加工家": "加工件",
            "弓箭": "工件",
            "网服": "往复",
            "磨学": "磨削",
            "通知流电": "通直流电",
            "吸捞": "吸牢",
            "沙轮": "砂轮",
            "变动机": "电动机",
            "划座": "滑座",
            "幻象开关": "换向开关",
            "解构": "结构",
            "金家宫": "精加工",
            "外园": "外圆",
            "内园": "内圆",
            "一块": "一款",
            "冲磁": "充磁",
            "驱磁": "去磁",
            "非配": "分配",
            "三项": "三相",
            "龙形": "笼型",
            "一部": "异步",
            "减化": "简化",
            "液压蹦": "液压泵",
            "网夫": "往复",
            "沙律": "砂轮",
            "镜给": "进给",
            "电极": "电机",
            "魔械": "磨屑",
            "严厉住": "沿立柱",
            "圣磁": "剩磁",
            "领压": "零压",
            "施压": "失压",
            "嵌压": "欠压",
            "犀利": "吸力",
            "举步": "局部",
            "魔场": "磨床",
            "屏面": "平面",
            "主触点必合": "主触点闭合",
            "正反撞": "正反转",
            "沙漏": "砂轮",
            "常触触点": "常闭触点",
            "场必触点": "常闭触点",
            "试电": "失电",
            "长开": "常开",
            "常开触点必合": "常开触点闭合",
            "长逼触点": "常闭触点",
            "同电": "通电",
            "底下": "抵消",
            "大电杆附在": "大电感负载",
            "二成": "而成",
            "电动式": "电动势",
            "集传": "击穿",
            "远见": "元件",
            "编组": "电阻",
            "缓解": "环节",
            "缉电器": "继电器",
            "眼中": "严重",
            "集力": "吸力",
            "损出来": "甩出来",
            "挺转": "停转",
            "环解": "环节",
            "控制电压器": "控制变压器",
            "照明等": "照明灯",
            "屏面磨闯": "平面磨床",
            "实读": "识读",
            "电型": "典型",
        }
    
    def load_srt(self, srt_path: str) -> List[Dict]:
        """加载SRT文件，返回字幕段列表"""
        segments = []
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    # 解析时间轴: 00:00:00,000 --> 00:00:00,000
                    time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
                    if time_match:
                        start_time = time_match.group(1)
                        end_time = time_match.group(2)
                        text = '\n'.join(lines[2:]).strip()
                        segments.append({
                            'index': int(lines[0]),
                            'start': start_time,
                            'end': end_time,
                            'text': text
                        })
        except Exception as e:
            raise Exception(f"加载SRT文件失败: {str(e)}")
        
        return segments
    
    def load_txt(self, txt_path: str) -> str:
        """加载逐字稿（支持txt、doc、docx）"""
        path = Path(txt_path)
        try:
            if path.suffix.lower() == '.docx':
                # 读取Word文档 (.docx)
                from docx import Document
                doc = Document(txt_path)
                paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                return '\n'.join(paragraphs)
            elif path.suffix.lower() == '.doc':
                # 读取旧版Word文档 (.doc)
                import win32com.client
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                try:
                    doc = word.Documents.Open(str(path.absolute()))
                    content = doc.Content.Text
                    doc.Close(False)
                    # 按换行符分割，去除空行
                    paragraphs = [p.strip() for p in content.split('\r\n') if p.strip()]
                    return '\n'.join(paragraphs)
                finally:
                    word.Quit()
            else:
                # 读取文本文件
                with open(txt_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except Exception as e:
            raise Exception(f"加载逐字稿失败: {str(e)}")
    
    def extract_text_from_srt(self, srt_segments: List[Dict]) -> str:
        """从SRT提取纯文本（按顺序拼接）"""
        texts = []
        for seg in srt_segments:
            texts.append(seg['text'])
        return '\n'.join(texts)
    
    def time_to_seconds(self, time_str: str) -> float:
        """将时间字符串转换为秒数"""
        match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        return 0.0
    
    def proofread(self, srt_path: str, transcript_path: str, 
                 progress_callback=None, log_callback=None) -> Tuple[str, Dict]:
        """
        校对字幕与逐字稿
        
        Returns:
            Tuple[校对报告路径, 统计信息]
        """
        if log_callback:
            log_callback(f"开始校对...")
            log_callback(f"字幕文件: {srt_path}")
            log_callback(f"逐字稿: {transcript_path}")
        
        # 加载文件
        srt_segments = self.load_srt(srt_path)
        transcript = self.load_txt(transcript_path)
        
        if log_callback:
            log_callback(f"加载完成: {len(srt_segments)} 个字幕段")
        
        if progress_callback:
            progress_callback(30, 100, "正在对比文本...")
        
        # 提取字幕文本
        subtitle_text = self.extract_text_from_srt(srt_segments)
        
        # 使用difflib进行对比
        subtitle_lines = subtitle_text.split('\n')
        transcript_lines = transcript.split('\n')
        
        diff_result = list(difflib.unified_diff(
            transcript_lines,
            subtitle_lines,
            fromfile='逐字稿',
            tofile='字幕',
            lineterm=''
        ))
        
        # 统计信息
        stats = self._calculate_stats(transcript_lines, subtitle_lines)
        
        if progress_callback:
            progress_callback(70, 100, "正在生成报告...")
        
        # 生成校对报告
        report = self._generate_report(
            srt_path, transcript_path,
            srt_segments, transcript,
            subtitle_lines, transcript_lines,
            diff_result, stats
        )
        
        # 保存报告
        report_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_校对报告.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        if log_callback:
            log_callback(f"✓ 校对完成")
            log_callback(f"  逐字稿行数: {stats['transcript_lines']}")
            log_callback(f"  字幕行数: {stats['subtitle_lines']}")
            log_callback(f"  新增行数: {stats['added_lines']}")
            log_callback(f"  删除行数: {stats['removed_lines']}")
            log_callback(f"  差异行数: {stats['diff_lines']}")
            log_callback(f"  报告已保存: {report_path}")
        
        if progress_callback:
            progress_callback(100, 100, "校对完成")
        
        return report_path, stats
    
    def _calculate_stats(self, transcript_lines: List[str], subtitle_lines: List[str]) -> Dict:
        """计算统计信息"""
        matcher = difflib.SequenceMatcher(None, transcript_lines, subtitle_lines)
        
        added = 0
        removed = 0
        changed = 0
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'insert':
                added += j2 - j1
            elif tag == 'delete':
                removed += i2 - i1
            elif tag == 'replace':
                changed += max(i2 - i1, j2 - j1)
        
        # 计算相似度
        similarity = matcher.ratio() * 100
        
        return {
            'transcript_lines': len(transcript_lines),
            'subtitle_lines': len(subtitle_lines),
            'added_lines': added,
            'removed_lines': removed,
            'changed_lines': changed,
            'diff_lines': added + removed + changed,
            'similarity': similarity
        }
    
    def _generate_report(self, srt_path: str, transcript_path: str,
                         srt_segments: List[Dict], transcript: str,
                         subtitle_lines: List[str], transcript_lines: List[str],
                         diff_result: List[str], stats: Dict) -> str:
        """生成校对报告"""
        lines = []
        
        # 报告头部
        lines.append("=" * 60)
        lines.append("               字幕与逐字稿校对报告")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"字幕文件: {srt_path}")
        lines.append(f"逐字稿: {transcript_path}")
        lines.append(f"校对时间: {self._get_current_time()}")
        lines.append("")
        
        # 统计摘要
        lines.append("-" * 60)
        lines.append("                     统计摘要")
        lines.append("-" * 60)
        lines.append(f"逐字稿行数:  {stats['transcript_lines']}")
        lines.append(f"字幕行数:    {stats['subtitle_lines']}")
        lines.append(f"新增行数:    {stats['added_lines']}")
        lines.append(f"删除行数:    {stats['removed_lines']}")
        lines.append(f"修改行数:    {stats['changed_lines']}")
        lines.append(f"差异总行数:  {stats['diff_lines']}")
        lines.append(f"文本相似度:  {stats['similarity']:.2f}%")
        lines.append("")
        
        # 逐字稿预览
        lines.append("-" * 60)
        lines.append("                     逐字稿内容（前20行）")
        lines.append("-" * 60)
        for i, line in enumerate(transcript_lines[:20], 1):
            lines.append(f"{i:3d}: {line}")
        if len(transcript_lines) > 20:
            lines.append(f"... (共 {len(transcript_lines)} 行)")
        lines.append("")
        
        # 字幕内容预览
        lines.append("-" * 60)
        lines.append("                     字幕内容（前20行）")
        lines.append("-" * 60)
        for i, line in enumerate(subtitle_lines[:20], 1):
            lines.append(f"{i:3d}: {line}")
        if len(subtitle_lines) > 20:
            lines.append(f"... (共 {len(subtitle_lines)} 行)")
        lines.append("")
        
        # 差异详情
        if diff_result:
            lines.append("-" * 60)
            lines.append("                     差异详情")
            lines.append("-" * 60)
            lines.append("(逐字稿 → 字幕 的变化)")
            lines.append("")
            for line in diff_result[:100]:  # 限制显示前100行差异
                if line.startswith('---') or line.startswith('+++'):
                    lines.append(f"\n{line}")
                elif line.startswith('-'):
                    lines.append(f"  [-] {line[1:]}")
                elif line.startswith('+'):
                    lines.append(f"  [+] {line[1:]}")
                else:
                    lines.append(f"      {line}")
            if len(diff_result) > 100:
                lines.append(f"\n... (差异共 {len(diff_result)} 行，显示前100行)")
        else:
            lines.append("-" * 60)
            lines.append("✓ 未发现显著差异")
            lines.append("")
        
        lines.append("")
        lines.append("=" * 60)
        lines.append("                        报告结束")
        lines.append("=" * 60)
        
        return '\n'.join(lines)
    
    def _get_current_time(self) -> str:
        """获取当前时间"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def proofread_and_correct(self, srt_path: str, transcript_path: str,
                          progress_callback=None, log_callback=None) -> Tuple[str, str, Dict]:
        """
        校对字幕并在字幕后用括号标注正确内容

        Args:
            srt_path: 字幕文件路径
            transcript_path: 逐字稿文件路径
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            Tuple[修正字幕路径, 校对报告路径, 统计信息]
        """
        if log_callback:
            log_callback(f"开始校对修正...")
            log_callback(f"字幕: {srt_path}")
            log_callback(f"逐字稿: {transcript_path}")

        # 加载文件
        srt_segments = self.load_srt(srt_path)
        transcript = self.load_txt(transcript_path)

        if log_callback:
            log_callback(f"加载完成: {len(srt_segments)} 字幕段")
            log_callback(f"AI批次大小: {self.ai_proofread_batch_size}")

        if progress_callback:
            progress_callback(20, 100, "对比文本...")

        # 按行分割
        transcript_lines = transcript.split('\n')

        # 修正后的字幕段
        corrected_segments = []
        # 差异记录
        diff_records = []

        for i, seg in enumerate(srt_segments):
            if progress_callback:
                progress_callback(20 + int(i / len(srt_segments) * 50), 100, f"处理段 {i+1}/{len(srt_segments)}")

            seg_text = seg['text'].strip()
            # 找对应逐字稿行（按顺序对应）
            transcript_line = transcript_lines[i] if i < len(transcript_lines) else ""

            # 对比字幕行和逐字稿行
            if seg_text != transcript_line and transcript_line:
                similarity = difflib.SequenceMatcher(None, seg_text, transcript_line).ratio()
                if similarity < 0.9:  # 低于90%相似度视为不一致
                    corrected_text = f"{seg_text}（{transcript_line}）"
                    diff_records.append({
                        'index': i + 1,
                        'subtitle': seg_text,
                        'transcript': transcript_line,
                        'similarity': similarity
                    })
                else:
                    corrected_text = seg_text
            else:
                corrected_text = seg_text

            corrected_segments.append({
                'index': seg['index'],
                'start': seg['start'],
                'end': seg['end'],
                'text': corrected_text
            })

        if progress_callback:
            progress_callback(70, 100, "生成文件...")

        # 生成修正版字幕
        corrected_srt_path = self._save_corrected_srt(srt_path, corrected_segments)

        # 生成校对报告
        report_path = self._generate_correction_report(
            srt_path, transcript_path,
            srt_segments, transcript_lines,
            diff_records
        )

        if progress_callback:
            progress_callback(100, 100, "完成")

        if log_callback:
            log_callback(f"✓ 校对修正完成")
            log_callback(f"  字幕段数: {len(srt_segments)}")
            log_callback(f"  差异处: {len(diff_records)}")
            log_callback(f"  修正字幕: {corrected_srt_path}")
            log_callback(f"  校对报告: {report_path}")

        stats = {
            'subtitle_lines': len(srt_segments),
            'transcript_lines': len(transcript_lines),
            'diff_count': len(diff_records),
            'similarity_avg': sum(d['similarity'] for d in diff_records) / len(diff_records) if diff_records else 100
        }

        return corrected_srt_path, report_path, stats

    def _save_corrected_srt(self, srt_path: str, segments: List[Dict]) -> str:
        """保存修正后的字幕文件"""
        lines = []
        for seg in segments:
            lines.append(str(seg['index']))
            lines.append(f"{seg['start']} --> {seg['end']}")
            lines.append(seg['text'])
            lines.append("")

        content = '\n'.join(lines)
        output_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_校对修正版.srt")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return output_path

    def _generate_correction_report(self, srt_path: str, transcript_path: str,
                                    srt_segments: List[Dict], transcript_lines: List[str],
                                    diff_records: List[Dict]) -> str:
        """生成校对报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("                     字幕校对报告")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"字幕文件: {srt_path}")
        lines.append(f"逐字稿: {transcript_path}")
        lines.append(f"校对时间: {self._get_current_time()}")
        lines.append("")

        # 统计
        lines.append("-" * 60)
        lines.append("                     统计信息")
        lines.append("-" * 60)
        lines.append(f"字幕段数: {len(srt_segments)}")
        lines.append(f"逐字稿行数: {len(transcript_lines)}")
        lines.append(f"差异处: {len(diff_records)}")
        lines.append("")

        # 差异详情
        if diff_records:
            lines.append("-" * 60)
            lines.append("                     差异详情")
            lines.append("-" * 60)
            for rec in diff_records:
                lines.append(f"段 {rec['index']}:")
                lines.append(f"  字幕: {rec['subtitle']}")
                lines.append(f"  逐字稿: {rec['transcript']}")
                lines.append(f"  相似度: {rec['similarity']*100:.1f}%")
                lines.append("")
        else:
            lines.append("✓ 未发现显著差异")

        lines.append("")
        lines.append("=" * 60)
        lines.append("                        报告结束")
        lines.append("=" * 60)

        report_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_校对报告.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return report_path

    def proofread_with_ai(self, srt_path: str, transcript_path: str,
                           progress_callback=None, log_callback=None) -> Tuple[str, str, Dict]:
        """
        使用AI语义匹配校对字幕，并按局部错误追加括号修正标注

        Args:
            srt_path: 字幕文件路径
            transcript_path: 逐字稿文件路径
            progress_callback: 进度回调
            log_callback: 日志回调

        Returns:
            Tuple[修正字幕路径, 校对报告路径, 统计信息]
        """
        if log_callback:
            log_callback(f"开始AI校对修正...")
            log_callback(f"字幕: {srt_path}")
            log_callback(f"逐字稿: {transcript_path}")

        # 加载文件
        srt_segments = self.load_srt(srt_path)
        transcript = self.load_txt(transcript_path)

        # 构建字幕段落列表
        subtitle_parts = []
        for seg in srt_segments:
            subtitle_parts.append(seg['text'].strip())

        if log_callback:
            log_callback(f"加载完成: {len(srt_segments)} 字幕段")

        if progress_callback:
            progress_callback(20, 100, "正在调用AI校对...")

        # 分批调用，避免整份长字幕一次性输入后模型只返回少量或空修改。
        all_ai_segments = []
        total_batches = max(1, (len(subtitle_parts) + self.ai_proofread_batch_size - 1) // self.ai_proofread_batch_size)

        for batch_no, start in enumerate(range(0, len(subtitle_parts), self.ai_proofread_batch_size), 1):
            end = min(start + self.ai_proofread_batch_size, len(subtitle_parts))
            batch_parts = subtitle_parts[start:end]
            subtitle_text = '\n'.join(
                [f"[段{start+i+1}] {text}" for i, text in enumerate(batch_parts)]
            )
            transcript_context = self._get_transcript_context(
                transcript,
                start,
                end,
                len(subtitle_parts)
            )

            if progress_callback:
                progress_callback(
                    20 + int((batch_no - 1) / total_batches * 35),
                    100,
                    f"正在调用AI校对 {batch_no}/{total_batches}..."
                )

            prompt = f"""你是字幕校对助手。请根据逐字稿，为字幕片段判断是否能找到语义对应内容，并提取可以明确定位的局部错词。

任务要求：
1. 先理解整份逐字稿和整份字幕，不要按行机械对齐。
2. 对每一段字幕，先判断能否在逐字稿中找到语义对应的内容。
3. 只要能明确定位到局部错误词语/短语，就给出修改建议。
4. 如果无法明确定位错词，或无法确认对应关系，必须跳过，不要猜。
5. 绝对不要整句改写，绝对不要返回润色后的句子，只返回局部错词映射。

输出格式：
- 只返回 JSON，不要解释，不要 Markdown 代码块。
- 返回一个对象，格式如下：
{{
  "segments": [
    {{
      "segment_index": 1,
      "matched": true,
      "confidence": "high",
      "aligned_transcript": "对应的逐字稿片段",
      "edits": [
        {{"wrong": "编织", "correct": "编制"}}
      ],
      "reason": "可明确定位错词"
    }}
  ]
}}

字段规则：
- segment_index: 字幕段号，从 1 开始
- matched: 是否找到语义对应内容
- confidence: 只能是 high / medium / low
- aligned_transcript: 找到的逐字稿对应片段，找不到时填空字符串
- edits: 仅包含可明确定位的局部错误。没有可安全修改的内容时返回空数组
- reason: 简短说明；如果跳过，要说明为什么跳过

判定规则：
- 程序只会采用 matched=true、confidence=high 或 medium、edits 非空的结果
- wrong 必须是字幕中实际出现的连续文本
- correct 必须是逐字稿中的对应正确文本
- 如果一段有多个明确错词，可返回多个 edits
- 如果 wrong 在字幕中并不存在，宁可不返回这个 edit
- 常见同音/近音识别错误应积极指出，例如：机电器→继电器、十度→识读、沙轮→砂轮、弓箭→工件、魔学→磨削、常逼→常闭

示例：
字幕：文字符号是用于电器技术领域中技术文件的编织
逐字稿对应：文字符号是用于电器技术领域中技术文件的编制
返回：
{{"segment_index": 1, "matched": true, "confidence": "high", "aligned_transcript": "文字符号是用于电器技术领域中技术文件的编制", "edits": [{{"wrong": "编织", "correct": "编制"}}], "reason": "末尾词语识别错误"}}

字幕内容（共{len(subtitle_parts)}段）：
{subtitle_text}

逐字稿参考片段：
{transcript_context}

请输出完整 JSON。"""

            if log_callback:
                log_callback(f"正在调用大模型 {translator_engine.get_translation_model()}: 批次 {batch_no}/{total_batches}")
                log_callback(f"提示词长度: {len(prompt)} 字符")

            # 调用AI
            try:
                corrected_text = self._call_minimax_ai(prompt, log_callback)
                if log_callback:
                    log_callback(f"AI返回长度: {len(corrected_text)} 字符")
            except Exception as e:
                if log_callback:
                    log_callback(f"AI调用失败: {str(e)}")
                raise

            try:
                batch_result = self._parse_ai_proofread_result(corrected_text, len(srt_segments))
                parsed_segments = batch_result.get('segments', [])
                all_ai_segments.extend(parsed_segments)
                if log_callback:
                    log_callback(f"批次 {batch_no}/{total_batches}: 解析到 {len(parsed_segments)} 段校对建议")
            except Exception as e:
                if log_callback:
                    log_callback(f"批次 {batch_no}/{total_batches} 解析失败，已跳过该批次: {str(e)}")
                continue

        if progress_callback:
            progress_callback(60, 100, "解析结果...")

        # 解析AI返回结果
        ai_segments = {item['segment_index']: item for item in all_ai_segments}
        if log_callback and not ai_segments:
            log_callback("AI未解析出可用的批次结果，将仅使用本地词典兜底生成校对版字幕")

        # 构建修正后的字幕段
        corrected_segments = []
        diff_count = 0
        aligned_count = 0
        skipped_count = 0
        diff_records = []

        for i, seg in enumerate(srt_segments):
            original_text = seg['text'].strip()
            ai_segment = ai_segments.get(i + 1, {})
            matched = bool(ai_segment.get('matched'))
            confidence = str(ai_segment.get('confidence', '')).lower()
            edits = ai_segment.get('edits') or []
            reason = ai_segment.get('reason', '')
            aligned_text = ai_segment.get('aligned_transcript', '')

            if matched:
                aligned_count += 1

            corrected_text_line, applied_edits = self._apply_local_annotations(
                original_text,
                edits,
                matched=matched,
                confidence=confidence
            )

            if applied_edits:
                diff_count += 1
                diff_records.append({
                    'index': i + 1,
                    'subtitle': original_text,
                    'aligned_transcript': aligned_text,
                    'corrected': corrected_text_line,
                    'edits': applied_edits,
                    'reason': reason or "局部修正"
                })
                if log_callback:
                    log_callback(f"段{i+1}: {corrected_text_line}")
            else:
                if matched and edits:
                    skipped_count += 1
                    if log_callback and reason:
                        log_callback(f"段{i+1} 跳过: {reason}")

            corrected_text_line, term_edits = self._apply_domain_term_annotations(
                corrected_text_line,
                transcript
            )
            if term_edits:
                if not applied_edits:
                    diff_count += 1
                diff_records.append({
                    'index': i + 1,
                    'subtitle': original_text,
                    'aligned_transcript': aligned_text,
                    'corrected': corrected_text_line,
                    'edits': term_edits,
                    'reason': "领域常见识别错误"
                })
                if log_callback:
                    log_callback(f"段{i+1}: {corrected_text_line}")

            corrected_segments.append({
                'index': seg['index'],
                'start': seg['start'],
                'end': seg['end'],
                'text': corrected_text_line
            })

        if progress_callback:
            progress_callback(80, 100, "生成文件...")

        # 生成修正版字幕
        corrected_srt_path = self._save_corrected_srt(srt_path, corrected_segments)

        # 生成校对报告
        report_path = self._generate_ai_report(
            srt_path, transcript_path,
            srt_segments, transcript,
            diff_records,
            aligned_count,
            skipped_count
        )

        if progress_callback:
            progress_callback(100, 100, "完成")

        if log_callback:
            log_callback(f"✓ AI校对修正完成")
            log_callback(f"  字幕段数: {len(srt_segments)}")
            log_callback(f"  对齐成功: {aligned_count}")
            log_callback(f"  差异处: {diff_count}")
            log_callback(f"  保守跳过: {skipped_count}")
            log_callback(f"  修正字幕: {corrected_srt_path}")
            log_callback(f"  校对报告: {report_path}")

        stats = {
            'subtitle_lines': len(srt_segments),
            'aligned_count': aligned_count,
            'diff_count': diff_count,
            'skipped_count': skipped_count,
        }

        return corrected_srt_path, report_path, stats

    def _parse_ai_proofread_result(self, ai_text: str, segment_count: int) -> Dict[str, Any]:
        """解析AI返回的结构化校对结果"""
        raw = ai_text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'(\{.*\})', raw, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
            else:
                raise Exception("AI返回的校对结果不是有效JSON")

        if not isinstance(data, dict):
            raise Exception("AI返回结果格式错误：根节点必须是对象")

        segments = data.get('segments')
        if not isinstance(segments, list):
            raise Exception("AI返回结果格式错误：缺少 segments 数组")

        normalized_segments = []
        for item in segments:
            if not isinstance(item, dict):
                continue
            segment_index = item.get('segment_index')
            if not isinstance(segment_index, int) or not (1 <= segment_index <= segment_count):
                continue

            edits = []
            for edit in item.get('edits') or []:
                if not isinstance(edit, dict):
                    continue
                wrong = str(edit.get('wrong', '')).strip()
                correct = str(edit.get('correct', '')).strip()
                if wrong and correct and wrong != correct:
                    edits.append({'wrong': wrong, 'correct': correct})

            normalized_segments.append({
                'segment_index': segment_index,
                'matched': bool(item.get('matched')),
                'confidence': str(item.get('confidence', 'low')).lower(),
                'aligned_transcript': str(item.get('aligned_transcript', '')).strip(),
                'edits': edits,
                'reason': str(item.get('reason', '')).strip()
            })

        return {'segments': normalized_segments}

    def _apply_local_annotations(self, original_text: str, edits: List[Dict[str, str]],
                                 matched: bool, confidence: str) -> Tuple[str, List[Dict[str, str]]]:
        """只在高置信度且可定位时，对原字幕做局部括号标注"""
        if not matched or confidence not in ('high', 'medium') or not edits:
            return original_text, []

        cursor = 0
        parts = []
        applied_edits = []

        for edit in edits:
            wrong = edit['wrong']
            correct = edit['correct']
            found_at = original_text.find(wrong, cursor)
            if found_at == -1:
                found_at = original_text.find(wrong)
            if found_at == -1:
                continue

            parts.append(original_text[cursor:found_at])
            annotated = f"{wrong}（{wrong}→{correct}）"
            parts.append(annotated)
            cursor = found_at + len(wrong)
            applied_edits.append({'wrong': wrong, 'correct': correct})

        if not applied_edits:
            return original_text, []

        parts.append(original_text[cursor:])
        return ''.join(parts), applied_edits

    def _apply_domain_term_annotations(self, text: str, transcript: str) -> Tuple[str, List[Dict[str, str]]]:
        """用领域词典补充标注明确的常见识别错误"""
        applied_edits = []
        corrected_text = text

        for wrong, correct in self.proofread_term_fixes.items():
            if wrong not in corrected_text:
                continue
            if correct not in transcript:
                continue
            if f"{wrong}（{wrong}→" in corrected_text:
                continue
            corrected_text = corrected_text.replace(wrong, f"{wrong}（{wrong}→{correct}）")
            applied_edits.append({'wrong': wrong, 'correct': correct})

        return corrected_text, applied_edits

    def _call_minimax_ai(self, prompt: str, log_callback=None) -> str:
        """调用MiniMax AI"""
        if log_callback:
            log_callback(f"  准备发送请求...")

        # 获取当前配置的模型
        model_key = translator_engine.get_translation_model()
        if model_key == "Google翻译(备用)":
            raise Exception("字幕校对需要使用设置里的大模型，请不要选择 Google翻译(备用)")
        if not translator_engine.MINIMAX_API_KEY:
            raise Exception("未配置 API密钥，请在设置中填写并保存")
        minimax_model = translator_engine.TRANSLATION_MODELS.get(model_key, "abab6.5s-chat")

        if log_callback:
            log_callback(f"  使用模型: {minimax_model}")

        payload = {
            "model": minimax_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 8000
        }

        max_attempts = 4
        retryable_codes = {429, 500, 502, 503, 504}
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                if log_callback:
                    log_callback(f"  构建请求... ({attempt}/{max_attempts})")
                req = urllib.request.Request(
                    f"{translator_engine.MINIMAX_BASE_URL}/chat/completions",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {translator_engine.MINIMAX_API_KEY}'
                    },
                    method='POST'
                )

                if log_callback:
                    log_callback(f"  发送请求到 {translator_engine.MINIMAX_BASE_URL}...")

                with urllib.request.urlopen(req, timeout=180) as response:
                    if log_callback:
                        log_callback(f"  收到响应，正在解析...")
                    result = json.loads(response.read().decode('utf-8'))
                    content = result['choices'][0]['message']['content'].strip()

                    if log_callback:
                        log_callback(f"  AI返回内容长度: {len(content)} 字符")

                    return content

            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else ''
                last_error = f"{model_key} HTTP {e.code}: {error_body[:200]}"
                if e.code not in retryable_codes or attempt == max_attempts:
                    raise Exception(last_error)
            except TimeoutError as e:
                last_error = f"请求超时: {str(e)}"
                if attempt == max_attempts:
                    raise Exception(last_error)
            except urllib.error.URLError as e:
                last_error = f"网络连接失败: {str(e)}"
                if attempt == max_attempts:
                    raise Exception(last_error)
            except Exception as e:
                last_error = f"{model_key} API调用失败: {str(e)}"
                if attempt == max_attempts:
                    raise Exception(last_error)

            wait_seconds = min(2 * attempt, 8)
            if log_callback:
                log_callback(f"  AI请求失败，{wait_seconds}秒后重试 ({attempt + 1}/{max_attempts}): {last_error}")
            time.sleep(wait_seconds)

        raise Exception(last_error or f"{model_key} API调用失败")

    def _get_transcript_context(self, transcript: str, start: int, end: int,
                                total_segments: int, max_chars: int = 9000) -> str:
        """按字幕批次位置截取逐字稿上下文，避免每批都发送全文导致超时"""
        if len(transcript) <= max_chars or total_segments <= 0:
            return transcript

        context_start_ratio = max(0, (start - self.ai_proofread_batch_size) / total_segments)
        context_end_ratio = min(1, (end + self.ai_proofread_batch_size) / total_segments)
        char_start = int(len(transcript) * context_start_ratio)
        char_end = int(len(transcript) * context_end_ratio)

        if char_end - char_start < max_chars:
            center = (char_start + char_end) // 2
            half = max_chars // 2
            char_start = max(0, center - half)
            char_end = min(len(transcript), char_start + max_chars)
            char_start = max(0, char_end - max_chars)

        context = transcript[char_start:char_end].strip()
        return context or transcript[:max_chars]

    def _generate_ai_report(self, srt_path: str, transcript_path: str,
                            srt_segments: List[Dict], transcript: str,
                            diff_records: List[Dict],
                            aligned_count: int,
                            skipped_count: int) -> str:
        """生成AI校对报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("               AI字幕校对报告")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"字幕文件: {srt_path}")
        lines.append(f"逐字稿: {transcript_path}")
        lines.append(f"校对时间: {self._get_current_time()}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("                     统计信息")
        lines.append("-" * 60)
        lines.append(f"字幕段数: {len(srt_segments)}")
        lines.append(f"对齐成功: {aligned_count}")
        lines.append(f"实际修正: {len(diff_records)}")
        lines.append(f"保守跳过: {skipped_count}")
        lines.append(f"校对方式: AI大模型对比")
        lines.append("")
        lines.append("-" * 60)
        lines.append("                     说明")
        lines.append("-" * 60)
        lines.append("本报告由AI大模型自动生成")
        lines.append("修正内容已在字幕中用括号标注")
        lines.append("仅在高置信度且可明确定位局部错误时才会修改")
        lines.append("")

        if diff_records:
            lines.append("-" * 60)
            lines.append("                     修正详情")
            lines.append("-" * 60)
            for record in diff_records:
                lines.append(f"段 {record['index']}:")
                lines.append(f"  原字幕: {record['subtitle']}")
                if record['aligned_transcript']:
                    lines.append(f"  对应逐字稿: {record['aligned_transcript']}")
                lines.append(f"  修正后: {record['corrected']}")
                edit_text = ', '.join(
                    [f"{edit['wrong']}→{edit['correct']}" for edit in record['edits']]
                )
                lines.append(f"  修改项: {edit_text}")
                lines.append(f"  说明: {record['reason']}")
                lines.append("")
        lines.append("")
        lines.append("=" * 60)
        lines.append("                        报告结束")
        lines.append("=" * 60)

        report_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_校对报告.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return report_path


proofread_engine = ProofreadEngine()
