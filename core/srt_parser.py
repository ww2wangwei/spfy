from typing import List, Dict, Optional
import re

class SRTItem:
    def __init__(self, index: int, start_time: float, end_time: float, text: str):
        self.index = index
        self.start_time = start_time
        self.end_time = end_time
        self.text = text
    
    def to_srt_line(self) -> str:
        return f"{self.index}\n{self.format_time(self.start_time)} --> {self.format_time(self.end_time)}\n{self.text}\n"
    
    @staticmethod
    def format_time(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        milliseconds = int((secs - int(secs)) * 1000)
        secs = int(secs)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    @staticmethod
    def parse_time(time_str: str) -> float:
        parts = time_str.split(':')
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds_parts = parts[2].split(',')
        seconds = float(seconds_parts[0])
        milliseconds = float(seconds_parts[1]) / 1000
        return hours * 3600 + minutes * 60 + seconds + milliseconds

class SRTParser:
    def parse(self, content: str) -> List[SRTItem]:
        lines = content.strip().split('\n')
        items = []
        i = 0
        
        while i < len(lines):
            if lines[i].strip().isdigit():
                try:
                    index = int(lines[i].strip())
                    i += 1
                    
                    if i < len(lines) and '-->' in lines[i]:
                        time_range = lines[i].strip()
                        i += 1
                        
                        text_parts = []
                        while i < len(lines) and lines[i].strip():
                            text_parts.append(lines[i].strip())
                            i += 1
                        
                        text = '\n'.join(text_parts)
                        start_str, end_str = time_range.split(' --> ')
                        start_time = SRTItem.parse_time(start_str)
                        end_time = SRTItem.parse_time(end_str)
                        
                        items.append(SRTItem(index, start_time, end_time, text))
                except:
                    pass
            i += 1
        
        return items
    
    def parse_file(self, file_path: str) -> List[SRTItem]:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return self.parse(content)
    
    def generate(self, items: List[SRTItem]) -> str:
        return '\n'.join([item.to_srt_line() for item in items]).strip() + '\n'
    
    def write_file(self, items: List[SRTItem], file_path: str):
        content = self.generate(items)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def get_total_duration(self, items: List[SRTItem]) -> float:
        if not items:
            return 0.0
        return max(item.end_time for item in items)
    
    def merge_short_segments(self, items: List[SRTItem], min_duration: float = 0.5) -> List[SRTItem]:
        if not items:
            return []
        
        merged = []
        current = items[0]
        
        for item in items[1:]:
            if (item.start_time - current.end_time) < min_duration and item.index == current.index + 1:
                current.end_time = item.end_time
                current.text += ' ' + item.text
            else:
                merged.append(current)
                current = item
        
        merged.append(current)
        
        for i, item in enumerate(merged, start=1):
            item.index = i
        
        return merged
    
    def split_long_segments(self, items: List[SRTItem], max_duration: float = 10.0) -> List[SRTItem]:
        result = []
        
        for item in items:
            if item.end_time - item.start_time <= max_duration:
                result.append(item)
            else:
                duration = item.end_time - item.start_time
                texts = re.split(r'[，。！？、]', item.text)
                texts = [t.strip() for t in texts if t.strip()]
                
                if not texts:
                    result.append(item)
                    continue
                
                segment_duration = duration / len(texts)
                current_time = item.start_time
                
                for i, text in enumerate(texts):
                    end_time = min(current_time + segment_duration, item.end_time)
                    result.append(SRTItem(0, current_time, end_time, text))
                    current_time = end_time
        
        for i, item in enumerate(result, start=1):
            item.index = i
        
        return result