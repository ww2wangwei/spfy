import csv
import json
import importlib
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

translator_engine = importlib.import_module('video_tool.core.translator_engine')


class TerminologyEngine:
    """英文字幕专业术语校对引擎"""

    def __init__(self):
        self.batch_size = 20

    def load_srt(self, srt_path: str) -> List[Dict]:
        segments = []
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        blocks = re.split(r'\n\s*\n', content.strip())
        for block in blocks:
            lines = block.strip().splitlines()
            if len(lines) < 3:
                continue
            time_match = re.match(
                r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                lines[1]
            )
            if not time_match:
                continue
            segments.append({
                'index': int(lines[0]),
                'start': time_match.group(1),
                'end': time_match.group(2),
                'text': '\n'.join(lines[2:]).strip()
            })
        return segments

    def load_glossary(self, glossary_path: str = None) -> Dict[str, str]:
        if not glossary_path:
            return {}

        path = Path(glossary_path)
        if not path.exists():
            raise Exception(f"术语词库不存在: {glossary_path}")

        if path.suffix.lower() == '.docx':
            from docx import Document
            doc = Document(glossary_path)
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        elif path.suffix.lower() == '.csv':
            return self._load_csv_glossary(glossary_path)
        else:
            with open(glossary_path, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f if line.strip()]

        glossary = {}
        for line in lines:
            parsed = self._parse_glossary_line(line)
            if parsed:
                source, target = parsed
                glossary[source] = target
        return glossary

    def _load_csv_glossary(self, glossary_path: str) -> Dict[str, str]:
        glossary = {}
        with open(glossary_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                source = row[0].strip()
                target = row[1].strip()
                if source and target:
                    glossary[source] = target
        return glossary

    def _parse_glossary_line(self, line: str) -> Tuple[str, str]:
        for sep in ['=>', '->', '=', '：', ':', '\t', ',']:
            if sep in line:
                left, right = line.split(sep, 1)
                left = left.strip()
                right = right.strip()
                if left and right:
                    return left, right
        return None

    def proofread_english_terms(self, srt_path: str, domain: str = "",
                                glossary_path: str = None,
                                progress_callback=None,
                                log_callback=None) -> Tuple[str, str, Dict]:
        if progress_callback:
            progress_callback(2, 100, "准备英文术语校对...")

        if log_callback:
            log_callback("开始英文术语校对...")
            log_callback(f"英文字幕: {srt_path}")
            log_callback(f"专业方向: {domain or '未填写'}")
            if glossary_path:
                log_callback(f"术语词库: {glossary_path}")
            else:
                log_callback("未提供术语词库，将根据专业方向自动调用AI校对")

        segments = self.load_srt(srt_path)
        glossary = self.load_glossary(glossary_path)

        if progress_callback:
            progress_callback(10, 100, "加载英文字幕和词库...")

        if log_callback:
            log_callback(f"加载完成: {len(segments)} 段英文字幕")
            log_callback(f"词库术语: {len(glossary)} 条")
            if not glossary and domain:
                log_callback(f"AI将按「{domain}」专业方向检查英文术语")

        ai_edits = self._collect_ai_edits(
            segments,
            domain,
            glossary,
            progress_callback=progress_callback,
            log_callback=log_callback
        )

        if progress_callback:
            progress_callback(75, 100, "应用术语标注...")

        corrected_segments = []
        records = []
        ai_edits_by_index = {item['segment_index']: item for item in ai_edits}

        for seg in segments:
            corrected_text = seg['text']
            applied = []

            corrected_text, glossary_edits = self._apply_glossary_annotations(corrected_text, glossary)
            applied.extend(glossary_edits)

            ai_item = ai_edits_by_index.get(seg['index'], {})
            corrected_text, local_ai_edits = self._apply_ai_annotations(
                corrected_text,
                ai_item.get('edits') or []
            )
            applied.extend(local_ai_edits)

            if applied:
                records.append({
                    'index': seg['index'],
                    'original': seg['text'],
                    'corrected': corrected_text,
                    'edits': applied
                })
                if log_callback:
                    log_callback(f"段{seg['index']}: {corrected_text}")

            corrected_segments.append({
                'index': seg['index'],
                'start': seg['start'],
                'end': seg['end'],
                'text': corrected_text
            })

        if progress_callback:
            progress_callback(90, 100, "保存结果...")

        output_path = self._save_srt(srt_path, corrected_segments)
        report_path = self._save_report(srt_path, domain, glossary_path, len(segments), records)

        stats = {
            'subtitle_lines': len(segments),
            'glossary_terms': len(glossary),
            'changed_segments': len(records),
            'changed_terms': sum(len(record['edits']) for record in records)
        }

        if progress_callback:
            progress_callback(100, 100, "英文术语校对完成")

        if log_callback:
            log_callback("✓ 英文术语校对完成")
            log_callback(f"  修改段数: {stats['changed_segments']}")
            log_callback(f"  修改术语: {stats['changed_terms']}")
            log_callback(f"  审阅字幕: {output_path}")
            log_callback(f"  校对报告: {report_path}")

        return output_path, report_path, stats

    def _collect_ai_edits(self, segments: List[Dict], domain: str,
                          glossary: Dict[str, str],
                          progress_callback=None,
                          log_callback=None) -> List[Dict]:
        if not domain and not glossary:
            return []

        all_edits = []
        total_batches = max(1, (len(segments) + self.batch_size - 1) // self.batch_size)
        glossary_text = '\n'.join([f"{k} = {v}" for k, v in list(glossary.items())[:200]])

        for batch_no, start in enumerate(range(0, len(segments), self.batch_size), 1):
            batch = segments[start:start + self.batch_size]
            subtitle_text = '\n'.join([f"[{seg['index']}] {seg['text']}" for seg in batch])

            if progress_callback:
                progress_callback(
                    15 + int((batch_no - 1) / total_batches * 55),
                    100,
                    f"AI术语校对 {batch_no}/{total_batches}，正在发送..."
                )

            prompt = f"""You are a professional English subtitle terminology proofreader.

Domain: {domain or "Use the glossary and infer the technical field from the subtitles."}

Task:
1. Check only professional terminology in the English subtitles.
2. Do not rewrite ordinary English, grammar, style, or sentence structure.
3. Return edits only when the current term is clearly wrong or nonstandard for the domain.
4. Prefer the provided glossary when it applies.
5. If unsure, skip it. Do not guess.

Output JSON only:
{{
  "segments": [
    {{
      "segment_index": 1,
      "edits": [
        {{"wrong": "sand wheel", "correct": "grinding wheel", "source": "domain"}}
      ],
      "reason": "standard technical term"
    }}
  ]
}}

Rules:
- wrong must be exact text that appears in that subtitle segment.
- correct should be the professional English term.
- source must be "glossary" or "domain".
- If a segment has no safe terminology edit, omit it from segments.
- Do not include Markdown fences or explanations.

Glossary:
{glossary_text or "(none)"}

Subtitle segments:
{subtitle_text}
"""
            if log_callback:
                log_callback(f"正在调用AI术语校对: 批次 {batch_no}/{total_batches}")

            response = self._call_minimax_ai(prompt, log_callback)

            if progress_callback:
                progress_callback(
                    15 + int((batch_no - 0.5) / total_batches * 55),
                    100,
                    f"AI术语校对 {batch_no}/{total_batches}，正在解析..."
                )

            result = self._parse_ai_result(response, len(segments))
            if log_callback:
                log_callback(f"批次 {batch_no}/{total_batches}: AI返回 {len(result)} 段术语建议")
            all_edits.extend(result)

        return all_edits

    def _call_minimax_ai(self, prompt: str, log_callback=None) -> str:
        model_key = translator_engine.get_translation_model()
        if model_key == "Google翻译(备用)":
            raise Exception("英文术语校对需要使用设置里的大模型，请不要选择 Google翻译(备用)")

        minimax_model = translator_engine.TRANSLATION_MODELS.get(model_key, "abab6.5s-chat")
        payload = {
            "model": minimax_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 6000
        }

        max_attempts = 4
        retryable_codes = {429, 500, 502, 503, 504}
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(
                    f"{translator_engine.MINIMAX_BASE_URL}/chat/completions",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {translator_engine.MINIMAX_API_KEY}'
                    },
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    return result['choices'][0]['message']['content'].strip()
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

    def _parse_ai_result(self, ai_text: str, segment_count: int) -> List[Dict]:
        raw = ai_text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r'(\{.*\})', raw, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group(1))

        items = []
        for item in data.get('segments', []):
            if not isinstance(item, dict):
                continue
            segment_index = item.get('segment_index')
            if not isinstance(segment_index, int) or not (1 <= segment_index <= segment_count):
                continue

            edits = []
            for edit in item.get('edits') or []:
                wrong = str(edit.get('wrong', '')).strip()
                correct = str(edit.get('correct', '')).strip()
                source = str(edit.get('source', 'domain')).strip() or 'domain'
                if wrong and correct and wrong != correct:
                    edits.append({'wrong': wrong, 'correct': correct, 'source': source})

            if edits:
                items.append({
                    'segment_index': segment_index,
                    'edits': edits,
                    'reason': str(item.get('reason', '')).strip()
                })
        return items

    def _apply_glossary_annotations(self, text: str, glossary: Dict[str, str]) -> Tuple[str, List[Dict]]:
        edits = [{'wrong': wrong, 'correct': correct, 'source': 'glossary'}
                 for wrong, correct in glossary.items()]
        return self._apply_ai_annotations(text, edits)

    def _apply_ai_annotations(self, text: str, edits: List[Dict]) -> Tuple[str, List[Dict]]:
        corrected = text
        applied = []

        for edit in edits:
            wrong = edit['wrong']
            correct = edit['correct']
            source = edit.get('source', 'domain')
            if wrong not in corrected:
                continue
            if f"{wrong} ({wrong} ->" in corrected:
                continue

            annotated = f"{wrong} ({wrong} -> {correct})"
            corrected = corrected.replace(wrong, annotated, 1)
            applied.append({'wrong': wrong, 'correct': correct, 'source': source})

        return corrected, applied

    def _save_srt(self, srt_path: str, segments: List[Dict]) -> str:
        lines = []
        for seg in segments:
            lines.append(str(seg['index']))
            lines.append(f"{seg['start']} --> {seg['end']}")
            lines.append(seg['text'])
            lines.append("")

        output_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_术语校对版.srt")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return output_path

    def _save_report(self, srt_path: str, domain: str, glossary_path: str,
                     segment_count: int, records: List[Dict]) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("                 英文字幕术语校对报告")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"英文字幕: {srt_path}")
        lines.append(f"专业方向: {domain or '未填写'}")
        lines.append(f"术语词库: {glossary_path or '未使用'}")
        lines.append(f"字幕段数: {segment_count}")
        lines.append(f"修改段数: {len(records)}")
        lines.append(f"修改术语: {sum(len(record['edits']) for record in records)}")
        lines.append("")

        if records:
            lines.append("-" * 60)
            lines.append("                     修改详情")
            lines.append("-" * 60)
            for record in records:
                lines.append(f"段 {record['index']}:")
                lines.append(f"  原字幕: {record['original']}")
                lines.append(f"  审阅版: {record['corrected']}")
                for edit in record['edits']:
                    lines.append(f"  - {edit['wrong']} -> {edit['correct']} ({edit['source']})")
                lines.append("")
        else:
            lines.append("未发现需要校对的专业术语。")

        lines.append("=" * 60)
        lines.append("                        报告结束")
        lines.append("=" * 60)

        report_path = str(Path(srt_path).parent / f"{Path(srt_path).stem}_术语校对报告.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return report_path


terminology_engine = TerminologyEngine()
