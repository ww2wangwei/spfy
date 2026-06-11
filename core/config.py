import os
import json
from pathlib import Path

class ConfigManager:
    def __init__(self):
        self.user_dir = Path.home()
        self.cache_dir = self.user_dir / ".video_tool_cache"
        self.config_path = self.cache_dir / "config.json"
        self.default_config = {
            "ffmpeg_path": "",
            "cache_dir": str(self.cache_dir),
            "default_language": "Chinese",
            "default_model": "small",
            "default_voice": "zh-CN-XiaoxiaoNeural",
            "speed_align": True,
            "max_speed": 1.3,
            "burn_acceleration": False,
            "log_level": "INFO"
        }
        self.config = self._load_config()
    
    def _load_config(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    return {**self.default_config, **loaded}
            except:
                return self.default_config.copy()
        return self.default_config.copy()
    
    def save_config(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def get(self, key):
        return self.config.get(key, self.default_config.get(key))
    
    def set(self, key, value):
        self.config[key] = value
        self.save_config()
    
    def get_cache_dir(self):
        return Path(self.config.get("cache_dir", str(self.cache_dir)))
    
    def get_ffmpeg_path(self):
        path = self.config.get("ffmpeg_path", "")
        if path and os.path.exists(path):
            return path
        return self._find_ffmpeg()
    
    def _find_ffmpeg(self):
        paths = [
            "ffmpeg",
            "C:\\ffmpeg\\bin\\ffmpeg.exe",
            str(self.user_dir / "ffmpeg" / "bin" / "ffmpeg.exe"),
            str(Path(__file__).parent.parent / "tools" / "ffmpeg.exe")
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return "ffmpeg"
    
    def ensure_cache_dir(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)

config_manager = ConfigManager()