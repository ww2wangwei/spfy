import os
import logging
from datetime import datetime
from pathlib import Path

class Logger:
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = str(Path.home() / ".video_tool_cache" / "logs")
        
        os.makedirs(log_dir, exist_ok=True)
        
        self.log_file = os.path.join(log_dir, f"video_tool_{datetime.now().strftime('%Y%m%d')}.log")
        
        self.logger = logging.getLogger('video_tool')
        self.logger.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
        
        self.ui_callback = None
    
    def set_ui_callback(self, callback):
        self.ui_callback = callback
    
    def debug(self, message):
        self.logger.debug(message)
    
    def info(self, message):
        self.logger.info(message)
        if self.ui_callback:
            self.ui_callback(message)
    
    def warning(self, message):
        self.logger.warning(message)
        if self.ui_callback:
            self.ui_callback(f"⚠ {message}")
    
    def error(self, message):
        self.logger.error(message)
        if self.ui_callback:
            self.ui_callback(f"✗ {message}")
    
    def critical(self, message):
        self.logger.critical(message)
        if self.ui_callback:
            self.ui_callback(f"✗✗ {message}")
    
    def get_log_file_path(self):
        return self.log_file

logger = Logger()