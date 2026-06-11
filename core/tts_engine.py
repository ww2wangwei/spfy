import os
import re
import asyncio
from edge_tts import Communicate
from typing import Optional, List

class TTSEngine:
    def __init__(self):
        self.voices = {
            "Chinese": [
                "zh-CN-XiaoxiaoNeural",
                "zh-CN-YunxiNeural",
                "zh-CN-YunxiaNeural",
                "zh-CN-YunyangNeural",
                "zh-CN-liaoning-XiaobeiNeural",
                "zh-CN-shaanxi-XiaoniNeural"
            ],
            "English": [
                "en-US-JennyNeural",
                "en-US-EmmaNeural",
                "en-US-GuyNeural",
                "en-GB-SoniaNeural",
                "en-GB-RyanNeural"
            ],
            "Japanese": [
                "ja-JP-NanamiNeural",
                "ja-JP-KeitaNeural"
            ],
            "Korean": [
                "ko-KR-SunHiNeural",
                "ko-KR-InJoonNeural"
            ],
            "French": [
                "fr-FR-JulieNeural",
                "fr-FR-HenriNeural"
            ],
            "German": [
                "de-DE-KatjaNeural",
                "de-DE-ConradNeural"
            ]
        }
        self.default_voice = "en-US-JennyNeural"
    
    def get_voices(self, language: str) -> List[str]:
        return self.voices.get(language, [])
    
    def get_all_voices(self) -> dict:
        return self.voices
    
    async def synthesize_segment(self, text: str, voice: str, output_path: str):
        """合成单个文本段的语音"""
        communicate = Communicate(text, voice)
        
        max_retries = 3
        retry_delay = 5  # 秒
        
        for attempt in range(max_retries):
            try:
                with open(output_path, "wb") as f:
                    async for chunk in communicate.stream():
                        if chunk['type'] == 'audio':
                            f.write(chunk['data'])
                return  # 成功，退出循环
            except Exception as e:
                if attempt < max_retries - 1:
                    import time
                    import logging
                    logging.warning(f"TTS attempt {attempt+1} failed, retrying in {retry_delay}s: {str(e)}")
                    await asyncio.sleep(retry_delay)
                else:
                    # 最后一次尝试失败，抛出异常
                    raise
    
    def generate_audio(self, text: str, voice: str = None, output_path: str = None, callback=None):
        if voice is None:
            voice = self.default_voice
        
        if output_path is None:
            import tempfile
            output_path = tempfile.mktemp(suffix='.mp3')
        
        try:
            if callback:
                callback(f"Synthesizing speech with voice: {voice}")
            
            asyncio.run(self.synthesize_segment(text, voice, output_path))
            
            if callback:
                callback(f"Audio saved to: {output_path}")
            
            return output_path
        except Exception as e:
            if callback:
                callback(f"TTS synthesis failed: {str(e)}")
            raise
    
    def generate_audio_from_srt(self, srt_content: str, voice: str = None, 
                                output_dir: str = None, callback=None,
                                speed_align: bool = False, max_speed: float = 1.5,
                                progress_callback=None, speed_multiplier: float = 1.0) -> tuple:
        """
        从SRT文件生成音频，保持音频时长和字幕时间戳严格一致
        
        关键规则：
        1. 统一速度调整：先判断整体情况，选择一个统一的朗读速度
           - 如果语音总时长 <= 字幕总时长：保持自然语速，读完后留白
           - 如果语音总时长 > 字幕总时长：统一加快速度（最大1.5倍）
        2. 保持语音和字幕时间戳严格对应
        3. 最终输出做一次时长校准，避免编码拼接误差造成超时
        
        Args:
            srt_content: SRT内容
            voice: 语音类型
            output_dir: 输出目录
            callback: 回调函数
            speed_align: 是否变速对齐
            max_speed: 最大速度（默认1.5倍）
            progress_callback: 进度回调
            speed_multiplier: 时间轴倍数（1.0=正常）
        
        Returns:
            (audio_path, original_srt_content) 元组
        """
        if voice is None:
            voice = self.default_voice
        
        if output_dir is None:
            import tempfile
            output_dir = tempfile.mkdtemp()
        
        segments = self._parse_srt(srt_content)
        temp_files = []
        merge_files = []
        segment_audio_files = []

        # 0. 预处理：分割过长的字幕段
        all_sub_segments = []
        for seg in segments:
            sub_segs = self._split_long_segment(seg, max_cps=8.0)
            all_sub_segments.extend(sub_segs)

        if len(all_sub_segments) != len(segments):
            if callback:
                callback(f"  Split {len(segments)} segments into {len(all_sub_segments)} sub-segments for better timing")

        try:
            total_segments = len(all_sub_segments)

            # 第一步：生成所有TTS音频
            if callback:
                callback(f"Generating {total_segments} speech segments...")
            
            actual_total_duration = 0.0
            for i, segment in enumerate(all_sub_segments, start=1):
                if callback:
                    callback(f"  Generating speech {i}/{total_segments}: {segment['text'][:30]}...")
                
                if progress_callback:
                    progress = int((i / total_segments) * 40)
                    progress_callback(progress, 100, f"Generating speech {i}/{total_segments}")
                
                # 生成TTS音频（保持自然语速）
                temp_path = os.path.join(output_dir, f"temp_{i:04d}.mp3")
                asyncio.run(self.synthesize_segment(segment['text'], voice, temp_path))
                
                actual_duration = self._get_audio_duration(temp_path)
                actual_total_duration += actual_duration
                
                segment_audio_files.append({
                    'path': temp_path,
                    'text': segment['text'],
                    'start': segment['start'],
                    'end': segment['end'],
                    'actual_duration': actual_duration
                })
            
            # 第二步：计算文字密度统计（用于自适应语速控制）
            effective_speed_multiplier = speed_multiplier if speed_multiplier > 0 else 1.0
            if all_sub_segments:
                target_total_duration = sum(
                    (seg['end'] - seg['start']) / effective_speed_multiplier
                    for seg in all_sub_segments
                )
                target_timeline_end = all_sub_segments[-1]['end'] / effective_speed_multiplier
            else:
                target_total_duration = 0.0
                target_timeline_end = 0.0

            # 计算每个段落的文字密度
            segment_cps_info = []
            for seg in all_sub_segments:
                target_dur = (seg['end'] - seg['start']) / effective_speed_multiplier
                cps = self._calculate_cps(seg['text'], target_dur)
                segment_cps_info.append({
                    'text': seg['text'],
                    'target_duration': target_dur,
                    'cps': cps
                })

            # 全局文字密度统计
            if segment_cps_info:
                avg_cps = sum(info['cps'] for info in segment_cps_info) / len(segment_cps_info)
                max_cps = max(info['cps'] for info in segment_cps_info)
                min_cps = min(info['cps'] for info in segment_cps_info)
            else:
                avg_cps = max_cps = min_cps = 0.0

            # 计算全局 tempo_ratio（提前到预计算之前）
            if speed_align and actual_total_duration > 0 and target_total_duration > 0:
                if actual_total_duration > target_total_duration:
                    tempo_ratio = actual_total_duration / target_total_duration
                    effective_max_speed = max(1.0, float(max_speed))
                    if tempo_ratio > effective_max_speed:
                        tempo_ratio = effective_max_speed
                else:
                    tempo_ratio = 1.0
            else:
                tempo_ratio = 1.0

            # 第三步：预计算每段需要的速度（用于后续平滑）
            segment_speeds = []
            for idx, seg_info in enumerate(segment_audio_files):
                target_duration = (seg_info['end'] - seg_info['start']) / effective_speed_multiplier

                if speed_align and target_duration > 0 and seg_info['actual_duration'] > 0:
                    # 计算该段的理想速度
                    required_speed = seg_info['actual_duration'] / target_duration

                    if required_speed > 1.0:
                        # 需要加速（自然朗读太慢，会超时）
                        # 速度范围：1.0 ~ min(tempo_ratio, 1.5)
                        max_sp = min(max(1.0, tempo_ratio), 1.5)
                        # 限制最大加速比，避免语速过快但允许处理极端情况
                        max_accel = min(max_sp, 1.5)
                        ideal_speed = min(required_speed, max_accel)
                        ideal_speed = max(1.0, ideal_speed)
                    else:
                        # 自然语速能在目标时间内读完，保持原速
                        # 剩余时间用静音留白补齐
                        ideal_speed = 1.0
                else:
                    ideal_speed = 1.0

                segment_speeds.append(ideal_speed)

            # 对速度进行平滑处理，避免相邻段速度差异过大
            if speed_align and len(segment_speeds) > 1:
                max_speed_diff = 0.15  # 相邻段最大速度差异
                smoothed_speeds = [segment_speeds[0]]

                for idx in range(1, len(segment_speeds)):
                    prev_speed = smoothed_speeds[idx - 1]
                    curr_speed = segment_speeds[idx]

                    # 如果速度差异过大，进行平滑
                    if abs(curr_speed - prev_speed) > max_speed_diff:
                        # 逐步调整，每次最多变化max_speed_diff
                        if curr_speed > prev_speed:
                            new_speed = prev_speed + max_speed_diff
                        else:
                            new_speed = prev_speed - max_speed_diff
                        smoothed_speeds.append(new_speed)
                    else:
                        smoothed_speeds.append(curr_speed)

                # 再次平滑，从后向前传播，让整体更均匀
                for iteration in range(2):
                    for idx in range(len(smoothed_speeds) - 2, -1, -1):
                        prev_speed = smoothed_speeds[idx + 1]
                        curr_speed = smoothed_speeds[idx]

                        if abs(curr_speed - prev_speed) > max_speed_diff:
                            if curr_speed > prev_speed:
                                smoothed_speeds[idx] = prev_speed + max_speed_diff
                            else:
                                smoothed_speeds[idx] = prev_speed - max_speed_diff

                if callback:
                    callback(f"--- Speed Smoothing ---")
                    callback(f"Original speeds: {[f'{s:.3f}' for s in segment_speeds[:5]]}...")
                    callback(f"Smoothed speeds: {[f'{s:.3f}' for s in smoothed_speeds[:5]]}...")

                segment_speeds = smoothed_speeds
            else:
                if callback:
                    callback(f"Speed smoothing disabled or single segment")

            if callback:
                callback(f"=== DEBUG INFO ===")
                callback(f"Number of segments: {len(all_sub_segments)}")
                callback(f"Last segment end time: {all_sub_segments[-1]['end'] if all_sub_segments else 0}s")
                callback(f"Speed multiplier: {effective_speed_multiplier}")
                callback(f"Total speech duration: {actual_total_duration:.2f}s")
                callback(f"Target speech duration (from SRT slots): {target_total_duration:.2f}s")
                callback(f"Target timeline end (from SRT): {target_timeline_end:.2f}s")
                callback(f"--- CPS Analysis ---")
                callback(f"Average CPS: {avg_cps:.2f} chars/sec")
                callback(f"CPS range: {min_cps:.2f} ~ {max_cps:.2f}")

            # 判断是否需要调整速度（使用自适应策略）
            if speed_align and actual_total_duration > 0 and target_total_duration > 0:
                if actual_total_duration > target_total_duration:
                    if callback:
                        callback(f"✓ SPEED ADJUSTMENT NEEDED (adaptive)!")
                        callback(f"  Global ratio: {tempo_ratio:.3f}x")
                        callback(f"  Will adjust per-segment based on text density")
                else:
                    if callback:
                        callback(f"✓ NO GLOBAL SPEED ADJUSTMENT")
                        callback(f"  Will use per-segment adaptive speed based on text density")
            else:
                if callback:
                    if speed_align:
                        callback(f"✗ Cannot calculate speed ratio")
                    else:
                        callback(f"Speed align disabled, using natural speaking speed")

            # 第三步（修正）：严格1:1同步 - 每段独立对齐到SRT时间戳
            if callback:
                callback(f"=== Strict 1:1 Sync Mode ===")

            for i, seg_info in enumerate(segment_audio_files, start=1):
                if callback:
                    callback(f"Processing segment {i}/{total_segments}...")

                if progress_callback:
                    progress = 50 + int((i / total_segments) * 40)
                    progress_callback(progress, 100, f"Processing segment {i}/{total_segments}")

                # 计算该段的目标时长（使用SRT时间戳，不累积）
                target_duration = (seg_info['end'] - seg_info['start']) / effective_speed_multiplier

                # 使用预计算并平滑后的速度
                final_speed = segment_speeds[i - 1] if i - 1 < len(segment_speeds) else 1.0

                # 应用速度调整
                if speed_align and target_duration > 0 and final_speed != 1.0:
                    adjusted_path = os.path.join(output_dir, f"adjusted_{i:04d}.mp3")
                    self._adjust_audio_speed(seg_info['path'], adjusted_path, final_speed)
                    seg_info['path'] = adjusted_path
                    temp_files.append(adjusted_path)

                # 严格对齐到目标时长
                aligned_path = os.path.join(output_dir, f"aligned_{i:04d}.mp3")
                actual_aligned = self._align_audio_to_duration(
                    seg_info['path'], aligned_path, target_duration,
                    speed_align=speed_align, max_speed=max_speed, callback=callback
                )
                merge_files.append(aligned_path)

                if callback:
                    actual_duration_check = self._get_audio_duration(aligned_path)
                    callback(f"    Seg {i} aligned: target={target_duration:.3f}s, actual={actual_duration_check:.3f}s, diff={actual_duration_check - target_duration:.3f}s")

            # 合并所有音频
            final_output = os.path.join(output_dir, "output.mp3")
            self._merge_audio_files(merge_files, final_output)

            # 第四步：输出时长校准（兜底防止编码拼接误差导致总时长偏长）
            if target_timeline_end > 0:
                self._calibrate_output_duration(final_output, target_timeline_end, callback)
            
            # 清理临时文件
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            for seg_info in segment_audio_files:
                if os.path.exists(seg_info['path']):
                    os.remove(seg_info['path'])
            
            if callback:
                callback(f"Final audio saved to: {final_output}")
                callback(f"Audio duration aligned to SRT timeline")
            
            # 返回音频路径和原始SRT内容（时间戳不变）
            return final_output, srt_content
        except Exception as e:
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            for seg_info in segment_audio_files:
                if os.path.exists(seg_info['path']):
                    os.remove(seg_info['path'])
            if callback:
                callback(f"TTS from SRT failed: {str(e)}")
            raise
    
    def _generate_silence(self, output_path: str, duration: float):
        """生成指定时长的静音音频"""
        import subprocess
        args = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', f'anullsrc=channel_layout=mono:sample_rate=24000:duration={duration}',
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y', output_path
        ]
        subprocess.run(args, capture_output=True, check=True)
    
    def _calculate_cps(self, text: str, duration: float) -> float:
        """
        计算文字密度（Characters Per Second）

        Args:
            text: 文本内容
            duration: 时长（秒）

        Returns:
            每秒字符数
        """
        if duration <= 0:
            return 0.0
        return len(text) / duration

    def _split_long_segment(self, segment: dict, max_cps: float = 8.0) -> List[dict]:
        """
        分割过长的字幕段

        如果文字密度过高，按标点符号分割成多个子段，并按比例分配时间。

        Args:
            segment: 包含 text, start, end 的字典
            max_cps: 最大允许的每秒字符数（英文约7-8）

        Returns:
            分割后的子段列表
        """
        text = segment['text']
        start = segment['start']
        end = segment['end']
        duration = end - start

        # 计算文字密度
        cps = len(text) / duration if duration > 0 else 0

        # 如果密度可接受，不需要分割
        if cps <= max_cps:
            return [segment]

        # 需要分割 - 找自然断句点
        # 英文断句符号
        split_patterns = [
            r'\.\s+',      # 句号后跟空格
            r',\s+',       # 逗号后跟空格
            r';\s+',       # 分号后跟空格
            r'!\s+',       # 感叹号后跟空格
            r'\?\s+',      # 问号后跟空格
        ]

        parts = [text]
        for pattern in split_patterns:
            new_parts = []
            for part in parts:
                if len(part) > 40:  # 只在较长的部分中继续分割
                    split_result = re.split(f'({pattern})', part)
                    combined = []
                    for i, item in enumerate(split_result):
                        if item in ('.', ',', ';', '!', '?') or re.match(pattern, item):
                            if combined:
                                combined[-1] += item
                            else:
                                combined.append(item)
                        else:
                            combined.append(item)
                    new_parts.extend([s.strip() for s in combined if s.strip()])
                else:
                    new_parts.append(part)
            parts = new_parts

        # 如果分割后仍然只有一个部分（没有找到断句点），按单词数强制分割
        if len(parts) == 1 and len(text) > 40:
            words = text.split()
            target_words_per_part = 8  # 每部分约8个单词
            parts = []
            current_chunk = []
            current_len = 0
            for word in words:
                if current_len + len(word) <= 50 and len(current_chunk) < target_words_per_part:
                    current_chunk.append(word)
                    current_len += len(word)
                else:
                    if current_chunk:
                        parts.append(' '.join(current_chunk))
                    current_chunk = [word]
                    current_len = len(word)
            if current_chunk:
                parts.append(' '.join(current_chunk))

        # 合并相邻过短的片段
        merged_parts = []
        buffer = ""
        for part in parts:
            if len(buffer) + len(part) <= 50:
                buffer += (" " if buffer else "") + part
            else:
                if buffer:
                    merged_parts.append(buffer)
                buffer = part
        if buffer:
            merged_parts.append(buffer)

        # 按比例分配时间
        total_chars = sum(len(p) for p in merged_parts)
        if total_chars == 0:
            return [segment]

        result = []
        current_time = start
        for part in merged_parts:
            part_chars = len(part)
            # 按字符数比例分配时间
            part_duration = (part_chars / total_chars) * duration
            result.append({
                'text': part,
                'start': current_time,
                'end': current_time + part_duration
            })
            current_time += part_duration

        return result

    def _adjust_audio_speed(self, input_path: str, output_path: str, speed_ratio: float):
        """
        调整音频速度
        speed_ratio > 1.0 表示加速（音频变短）
        speed_ratio < 1.0 表示减速（音频变长）
        """
        import subprocess

        # 使用atempo滤镜调整速度
        # atempo只接受0.5-2.0的范围，需要链式处理
        tempo_filters = []
        remaining_ratio = speed_ratio

        while remaining_ratio > 2.0:
            tempo_filters.append('atempo=2.0')
            remaining_ratio /= 2.0
        while remaining_ratio < 0.5:
            tempo_filters.append('atempo=0.5')
            remaining_ratio /= 0.5
        if remaining_ratio != 1.0:
            tempo_filters.append(f'atempo={remaining_ratio:.4f}')

        if not tempo_filters:
            # 不需要调整，直接复制
            import shutil
            shutil.copy(input_path, output_path)
            return

        filter_str = ','.join(tempo_filters)

        args = [
            'ffmpeg',
            '-i', input_path,
            '-af', filter_str,
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y', output_path
        ]
        subprocess.run(args, capture_output=True, check=True)
    
    def _truncate_audio(self, input_path: str, output_path: str, duration: float):
        """截断音频到指定时长"""
        import subprocess
        args = [
            'ffmpeg',
            '-i', input_path,
            '-t', str(duration),
            '-ac', '1',
            '-ar', '24000',
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y', output_path
        ]
        subprocess.run(args, capture_output=True, check=True)
    
    def _generate_new_srt(self, segments: List[dict], actual_durations: List[float], gaps: List[float], 
                          original_start_time: float = 0.0) -> str:
        """
        根据实际音频时长重新生成SRT文件
        按顺序拼接，段之间保留原SRT中的间隔
        保留原始SRT的起始时间偏移
        
        Args:
            segments: SRT片段列表
            actual_durations: 实际音频时长列表
            gaps: 段间间隔列表
            original_start_time: 原始SRT的起始时间偏移
        """
        new_srt_lines = []
        
        current_time = 0.0
        
        for i, (segment, actual_duration, gap) in enumerate(zip(segments, actual_durations, gaps), start=1):
            # 新的开始时间 = 当前时间 + 间隔
            new_start = current_time + gap
            new_end = new_start + actual_duration
            
            # 格式化时间（加上原始起始时间偏移）
            start_str = self._format_time(new_start + original_start_time)
            end_str = self._format_time(new_end + original_start_time)
            
            # 写入SRT条目
            new_srt_lines.append(str(i))
            new_srt_lines.append(f"{start_str} --> {end_str}")
            new_srt_lines.append(segment['text'])
            new_srt_lines.append("")  # 空行分隔
            
            # 更新当前时间（跳过静音时间，只记录语音时间）
            current_time = new_end
        
        return '\n'.join(new_srt_lines)
    
    def _format_time(self, seconds: float) -> str:
        """将秒数格式化为SRT时间格式 HH:MM:SS,mmm"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    def _parse_srt(self, srt_content: str) -> List[dict]:
        lines = srt_content.strip().split('\n')
        segments = []
        i = 0
        
        while i < len(lines):
            if lines[i].strip().isdigit():
                idx = int(lines[i].strip())
                i += 1
                
                if i < len(lines) and '-->' in lines[i]:
                    time_range = lines[i].strip()
                    i += 1
                    
                    text_parts = []
                    while i < len(lines) and lines[i].strip():
                        text_parts.append(lines[i].strip())
                        i += 1
                    text = ' '.join(text_parts)
                    
                    start_time, end_time = self._parse_time(time_range)
                    duration = end_time - start_time
                    
                    segments.append({
                        'index': idx,
                        'start': start_time,
                        'end': end_time,
                        'duration': duration,
                        'text': text
                    })
            i += 1
        
        return segments
    
    def _parse_time(self, time_str: str) -> tuple:
        """解析时间范围字符串，返回 (开始时间, 结束时间)"""
        parts = time_str.split(' --> ')
        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}")
        
        def parse_single_time(t: str) -> float:
            """解析单个时间字符串 00:00:00,000 -> 秒数"""
            h, m, s_ms = t.split(':')
            s, ms = s_ms.split(',')
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        
        start_time = parse_single_time(parts[0].strip())
        end_time = parse_single_time(parts[1].strip())
        return start_time, end_time
    
    def _get_audio_duration(self, audio_path: str) -> float:
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=nokey=1:noprint_wrappers=1', audio_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except:
            pass
        return 0.0
    
    def _speed_audio(self, input_path: str, output_path: str, speed: float):
        import subprocess
        args = [
            'ffmpeg', '-i', input_path,
            '-filter:a', f'atempo={speed}',
            '-y', output_path
        ]
        subprocess.run(args, capture_output=True)
    
    def _merge_audio_files(self, input_files: List[str], output_path: str):
        import subprocess
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            for file_path in input_files:
                f.write(f"file '{file_path}'\n")
            list_file = f.name
        
        args = [
            'ffmpeg', '-f', 'concat',
            '-safe', '0',
            '-i', list_file,
            '-ac', '1',
            '-ar', '24000',
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-y', output_path
        ]
        try:
            subprocess.run(args, capture_output=True, check=True)
        finally:
            os.remove(list_file)
    
    def _calibrate_output_duration(self, output_path: str, target_duration: float, callback=None):
        actual_duration = self._get_audio_duration(output_path)
        tolerance = 0.03
        
        if actual_duration <= 0 or target_duration <= 0:
            return
        
        if actual_duration > target_duration + tolerance:
            trimmed_path = f"{output_path}.trimmed.mp3"
            self._truncate_audio(output_path, trimmed_path, target_duration)
            if os.path.exists(trimmed_path):
                os.replace(trimmed_path, output_path)
            if callback:
                callback(f"Final calibration: trimmed {actual_duration:.3f}s -> {target_duration:.3f}s")
        elif actual_duration < target_duration - tolerance:
            if callback:
                callback(f"Final audio is shorter than SRT timeline: {actual_duration:.3f}s < {target_duration:.3f}s")

    def _align_audio_to_duration(self, input_path: str, output_path: str,
                                  target_duration: float, speed_align: bool = True,
                                  max_speed: float = 1.5, callback=None) -> float:
        """
        将音频调整到精确的目标时长（严格1:1同步核心）

        策略：
        1. 如果音频时长≈目标时长（误差<0.05s），直接使用
        2. 如果音频时长 < 目标时长：加速或添加静音补齐
        3. 如果音频时长 > 目标时长：加速后截断

        Returns:
            实际调整后的音频时长
        """
        actual_duration = self._get_audio_duration(input_path)
        tolerance = 0.05 # 50ms容差

        # 情况1：音频时长在容差范围内，直接使用
        if abs(actual_duration - target_duration) <= tolerance:
            import shutil
            shutil.copy(input_path, output_path)
            return actual_duration

        # 情况2：音频太短，需要拉伸或补静音
        if actual_duration < target_duration:
            if speed_align:
                speed_ratio = actual_duration / target_duration
                if speed_ratio < 1.0:
                    effective_ratio = max(1.0, min(1.0 / speed_ratio, max_speed))
                else:
                    effective_ratio = 1.0

                if effective_ratio > 1.05:
                    adjusted_path = f"{input_path}.temp.mp3"
                    self._adjust_audio_speed(input_path, adjusted_path, effective_ratio)
                    adjusted_duration = self._get_audio_duration(adjusted_path)

                    if abs(adjusted_duration - target_duration) <= tolerance:
                        import shutil
                        shutil.move(adjusted_path, output_path)
                        return adjusted_duration
                    elif adjusted_duration > target_duration:
                        self._truncate_audio(adjusted_path, output_path, target_duration)
                        os.remove(adjusted_path)
                        return target_duration
                    else:
                        self._add_silence_to_fill(adjusted_path, output_path, target_duration)
                        os.remove(adjusted_path)
                        return target_duration
                else:
                    self._add_silence_to_fill(input_path, output_path, target_duration)
                    return target_duration
            else:
                self._add_silence_to_fill(input_path, output_path, target_duration)
                return target_duration

        # 情况3：音频太长，需要压缩
        if actual_duration > target_duration:
            if speed_align:
                speed_ratio = target_duration / actual_duration
                effective_ratio = max(1.0, min(1.0 / speed_ratio, max_speed))

                if effective_ratio > 1.05:
                    adjusted_path = f"{input_path}.temp.mp3"
                    self._adjust_audio_speed(input_path, adjusted_path, effective_ratio)
                    adjusted_duration = self._get_audio_duration(adjusted_path)

                    if adjusted_duration >= target_duration - tolerance:
                        self._truncate_audio(adjusted_path, output_path, target_duration)
                        os.remove(adjusted_path)
                        return target_duration
                    else:
                        self._add_silence_to_fill(adjusted_path, output_path, target_duration)
                        os.remove(adjusted_path)
                        return target_duration
                else:
                    self._truncate_audio(input_path, output_path, target_duration)
                    return target_duration
            else:
                self._truncate_audio(input_path, output_path, target_duration)
                return target_duration

        import shutil
        shutil.copy(input_path, output_path)
        return actual_duration

    def _add_silence_to_fill(self, input_path: str, output_path: str, target_duration: float):
        """添加静音使音频达到目标时长"""
        actual = self._get_audio_duration(input_path)
        silence_duration = target_duration - actual

        if silence_duration <= 0:
            import shutil
            shutil.copy(input_path, output_path)
            return

        silence_path = f"{input_path}.silence.mp3"
        self._generate_silence(silence_path, silence_duration)

        list_file = f"{input_path}.list.txt"
        with open(list_file, 'w') as f:
            f.write(f"file '{input_path}'\n")
            f.write(f"file '{silence_path}'\n")

        import subprocess
        args = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', '-y', output_path]
        subprocess.run(args, capture_output=True)
        os.remove(list_file)
        if os.path.exists(silence_path):
            os.remove(silence_path)

    def generate_audio_from_srt_strict(self, srt_content: str, voice: str = None,
                                       output_dir: str = None, callback=None,
                                       progress_callback=None,
                                       max_speed: float = 1.5,
                                       speed_align: bool = True) -> tuple:
        """
        严格1:1同步版本的SRT转MP3

        每段音频时长 = SRT_end - SRT_start
        音频太短 → 加速 + 静音补齐
        音频太长 → 截断
        """
        if voice is None:
            voice = self.default_voice

        if output_dir is None:
            import tempfile
            output_dir = tempfile.mkdtemp()

        segments = self._parse_srt(srt_content)

        if callback:
            callback(f"=== Strict 1:1 Sync (max_speed={max_speed}) ===")
            callback(f"Segments: {len(segments)}")

        try:
            total = len(segments)
            aligned_files = []

            for i, seg in enumerate(segments, start=1):
                text = seg['text'].strip()
                start_time = seg['start']
                end_time = seg['end']
                target_duration = end_time - start_time

                if progress_callback:
                    progress_callback(int((i / total) * 80), 100, f"Processing {i}/{total}")

                if not text:
                    silence_file = os.path.join(output_dir, f"sil_{i:04d}.mp3")
                    self._generate_silence(silence_file, target_duration)
                    aligned_files.append(silence_file)
                    if callback:
                        callback(f"  Seg {i}: empty -> {target_duration:.3f}s silence")
                    continue

                # 生成TTS
                raw_file = os.path.join(output_dir, f"raw_{i:04d}.mp3")
                asyncio.run(self.synthesize_segment(text, voice, raw_file))
                raw_duration = self._get_audio_duration(raw_file)

                # 对齐（使用max_speed加速）
                aligned_file = os.path.join(output_dir, f"seg_{i:04d}.mp3")
                actual = self._strict_align_to_file(raw_file, aligned_file, target_duration, max_speed, speed_align)
                aligned_files.append(aligned_file)

                if callback:
                    diff = actual - target_duration
                    callback(f"  Seg {i}: target={target_duration:.3f}s, actual={actual:.3f}s, diff={diff:+.3f}s")

            # 合并 - 按时间轴顺序
            final_output = os.path.join(output_dir, "output.mp3")
            self._merge_with_timeline(segments, aligned_files, final_output, callback)

            # 清理
            for f in aligned_files:
                if os.path.exists(f):
                    os.remove(f)

            if progress_callback:
                progress_callback(100, 100, "Done")

            if callback:
                callback(f"Done: {final_output}")

            return final_output, srt_content

        except Exception as e:
            if callback:
                callback(f"Failed: {str(e)}")
            raise

    def _strict_align_to_file(self, input_path: str, output_path: str, target_duration: float,
                               max_speed: float = 1.5, speed_align: bool = True) -> float:
        """严格对齐到目标时长，返回实际时长

        策略：
        1. 如果音频时长≈目标时长（<50ms差异），直接使用
        2. 如果音频太短且speed_align=True：
           - 先尝试加速（最大max_speed倍）
           - 如果加速后仍不够，添加静音补齐
        3. 如果音频太长：截断
        """
        import shutil
        actual = self._get_audio_duration(input_path)

        if abs(actual - target_duration) <= 0.05:
            shutil.copy(input_path, output_path)
            return actual

        if actual < target_duration:
            # 音频太短，尝试加速
            if speed_align and max_speed > 1.0 and actual > 0:
                speed_ratio = target_duration / actual
                if speed_ratio > 1.0:
                    effective_speed = min(speed_ratio, max_speed)
                    speed_file = f"{input_path}.spd.mp3"
                    self._adjust_audio_speed(input_path, speed_file, effective_speed)
                    actual2 = self._get_audio_duration(speed_file)

                    if abs(actual2 - target_duration) <= 0.05:
                        shutil.move(speed_file, output_path)
                        return actual2
                    elif actual2 > target_duration:
                        # 加速后太长，截断
                        self._truncate_audio(speed_file, output_path, target_duration)
                        os.remove(speed_file)
                        return target_duration
                    else:
                        # 加速后仍太短，添加静音
                        os.remove(speed_file)
                        self._add_silence_to_file(input_path, output_path, target_duration)
                        return target_duration

            # 不加速或无法加速，添加静音
            self._add_silence_to_file(input_path, output_path, target_duration)
            return target_duration
        else:
            # 太长：截断
            self._truncate_audio(input_path, output_path, target_duration)
            return target_duration

    def _add_silence_to_file(self, input_path: str, output_path: str, target_duration: float):
        """在音频末尾添加静音到目标时长"""
        import shutil
        actual = self._get_audio_duration(input_path)
        silence_dur = target_duration - actual

        if silence_dur <= 0:
            shutil.copy(input_path, output_path)
            return

        silence_file = f"{input_path}.sil.mp3"
        self._generate_silence(silence_file, silence_dur)

        list_file = f"{input_path}.lst"
        with open(list_file, 'w') as f:
            f.write(f"file '{input_path}'\n")
            f.write(f"file '{silence_file}'\n")

        import subprocess
        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', list_file, '-c', 'copy', '-y', output_path
        ], capture_output=True)

        os.remove(list_file)
        if os.path.exists(silence_file):
            os.remove(silence_file)

    def _merge_with_timeline(self, segments: list, aligned_files: list, output_path: str, callback=None):
        """
        按SRT时间轴合并音频（严格1:1同步）

        关键：
        1. 第一段开始时间前添加静音
        2. 每段音频结束后，填充静音直到下一段开始时间
        """
        import subprocess
        import tempfile

        if callback:
            callback(f"=== Merging with timeline sync ===")

        all_files = []
        total_files = []

        for i, (seg, audio_file) in enumerate(zip(segments, aligned_files)):
            start_time = seg['start']
            end_time = seg['end']

            # 如果是第一段且开始时间>0，添加前置静音
            if i == 0 and start_time > 0:
                lead_silence = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                lead_silence.close()
                self._generate_silence(lead_silence.name, start_time)
                all_files.append(lead_silence.name)
                total_files.append(lead_silence.name)
                if callback:
                    callback(f"  Added {start_time:.3f}s lead silence")

            # 添加当前段的音频
            all_files.append(audio_file)
            total_files.append(audio_file)

            # 如果不是最后一段，计算到下一段开始时间的间隔
            if i < len(segments) - 1:
                next_start = segments[i + 1]['start']
                gap = next_start - end_time
                if gap > 0.01:  # 超过10ms的间隔
                    gap_silence = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
                    gap_silence.close()
                    self._generate_silence(gap_silence.name, gap)
                    all_files.append(gap_silence.name)
                    total_files.append(gap_silence.name)
                    if callback:
                        callback(f"  Seg {i+1}: added {gap:.3f}s gap silence")

        # 合并所有文件
        list_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8'
        )
        for f in total_files:
            list_file.write(f"file '{f}'\n")
        list_file.close()

        if callback:
            callback(f"  Total files to merge: {len(total_files)}")

        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', list_file.name,
            '-ac', '1', '-ar', '24000',
            '-c:a', 'libmp3lame', '-b:a', '128k',
            '-y', output_path
        ], capture_output=True, check=True)

        os.remove(list_file.name)

        # 清理临时静音文件
        for f in all_files:
            if f != output_path and os.path.exists(f):
                # 只清理我们创建的静音文件，不清理aligned_files
                if 'sil' in f or 'gap' in f:
                    os.remove(f)

    def _merge_concat(self, input_files: list, output_path: str):
        """使用ffmpeg concat合并音频"""
        import subprocess
        import tempfile

        list_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8'
        )
        for f in input_files:
            list_file.write(f"file '{f}'\n")
        list_file.close()

        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', list_file.name,
            '-ac', '1', '-ar', '24000',
            '-c:a', 'libmp3lame', '-b:a', '128k',
            '-y', output_path
        ], capture_output=True, check=True)

        os.remove(list_file.name)
