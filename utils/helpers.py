import os
import shutil
from pathlib import Path

def get_file_size(file_path: str) -> str:
    """获取文件大小（传入文件路径）"""
    try:
        size = os.path.getsize(file_path)
        return format_size(size)
    except:
        return "Unknown"

def format_size(size: int) -> str:
    """格式化文件大小（传入字节数）"""
    try:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.2f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"
    except:
        return "Unknown"

def get_dir_size(dir_path: str) -> str:
    try:
        if not os.path.exists(dir_path):
            return "0 B"
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        return format_size(total_size)
    except:
        return "Unknown"

def clear_directory(dir_path: str):
    if os.path.exists(dir_path):
        for item in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

def is_valid_path(path: str) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve()
        return True
    except:
        return False

def sanitize_filename(filename: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename

def open_file_explorer(path: str):
    import subprocess
    if os.name == 'nt':
        subprocess.run(['explorer.exe', path])
    elif os.name == 'posix':
        subprocess.run(['open', path])

def get_audio_duration(audio_path: str) -> float:
    try:
        import subprocess
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', audio_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        import json
        info = json.loads(result.stdout)
        for stream in info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                return float(stream.get('duration', 0))
    except:
        pass
    return 0.0

def format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"