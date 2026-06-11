import os
from pathlib import Path
from typing import List, Tuple, Optional

class FileMatcher:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
    
    def find_mute_mp4_files(self) -> List[Path]:
        return list(self.base_dir.rglob('*-mute.mp4'))
    
    def find_new_mp4_files(self) -> List[Path]:
        return list(self.base_dir.rglob('*-new.mp4'))
    
    def find_mp3_files(self) -> List[Path]:
        return list(self.base_dir.rglob('*.mp3'))
    
    def find_srt_files(self) -> List[Path]:
        return list(self.base_dir.rglob('*.srt'))
    
    def find_original_mp4_files(self) -> List[Path]:
        files = []
        for mp4 in self.base_dir.rglob('*.mp4'):
            if '-mute.mp4' not in str(mp4) and '-new.mp4' not in str(mp4) and '_final.mp4' not in str(mp4):
                files.append(mp4)
        return files
    
    def match_mute_with_mp3(self) -> List[Tuple[Path, Path]]:
        matches = []
        mute_files = self.find_mute_mp4_files()
        
        for mute_file in mute_files:
            base_name = mute_file.stem.replace('-mute', '')
            mp3_path = mute_file.parent / f"{base_name}.mp3"
            
            if mp3_path.exists():
                matches.append((mute_file, mp3_path))
        
        return matches
    
    def match_new_with_srt(self) -> List[Tuple[Path, Path]]:
        matches = []
        new_files = self.find_new_mp4_files()
        
        for new_file in new_files:
            base_name = new_file.stem.replace('-new', '')
            srt_path = new_file.parent / f"{base_name}.srt"
            
            if srt_path.exists():
                matches.append((new_file, srt_path))
        
        return matches
    
    def find_original_for_mute(self, mute_file: Path) -> Optional[Path]:
        base_name = mute_file.stem.replace('-mute', '')
        original_path = mute_file.parent / f"{base_name}.mp4"
        
        if original_path.exists():
            return original_path
        return None
    
    def find_srt_for_mp3(self, mp3_file: Path) -> Optional[Path]:
        srt_path = mp3_file.parent / f"{mp3_file.stem}.srt"
        
        if srt_path.exists():
            return srt_path
        return None
    
    def get_output_path(self, input_path: Path, suffix: str) -> Path:
        return input_path.parent / f"{input_path.stem}{suffix}"