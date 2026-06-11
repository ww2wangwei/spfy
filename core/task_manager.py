import threading
import queue
from typing import Callable, Any, Optional

class TaskManager:
    def __init__(self):
        self.task_queue = queue.Queue()
        self.worker_thread = None
        self.is_running = False
        self.lock = threading.Lock()
        self.current_task = None
        self.progress_callback = None
        self.log_callback = None
        self.stop_requested = False

    def start(self):
        with self.lock:
            if not self.is_running:
                self.is_running = True
                self.worker_thread = threading.Thread(target=self._worker, daemon=True)
                self.worker_thread.start()

    def stop(self):
        with self.lock:
            self.is_running = False
        if self.worker_thread:
            self.task_queue.put(None)
            self.worker_thread.join(timeout=5)

    def request_stop(self):
        """请求停止当前任务"""
        with self.lock:
            self.stop_requested = True

    def check_stop(self) -> bool:
        """检查是否请求停止"""
        with self.lock:
            return self.stop_requested

    def reset_stop(self):
        """重置停止标志"""
        with self.lock:
            self.stop_requested = False

    def _worker(self):
        while self.is_running:
            task = self.task_queue.get()
            if task is None:
                break

            try:
                func, args, kwargs = task
                self.current_task = func.__name__

                if self.log_callback:
                    self.log_callback(f"Starting task: {self.current_task}")

                func(*args, **kwargs)

                if self.log_callback:
                    self.log_callback(f"Completed task: {self.current_task}")
            except Exception as e:
                if self.log_callback:
                    self.log_callback(f"Task {self.current_task} failed: {str(e)}")
            finally:
                self.current_task = None
                self.task_queue.task_done()
                self.reset_stop()

    def submit_task(self, func: Callable, *args, **kwargs):
        if self.is_running:
            self.task_queue.put((func, args, kwargs))
            return True
        return False

    def set_progress_callback(self, callback: Callable[[int, int, str], None]):
        self.progress_callback = callback

    def set_log_callback(self, callback: Callable[[str], None]):
        self.log_callback = callback

    def report_progress(self, current: int, total: int, message: str = ""):
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def is_busy(self) -> bool:
        return self.current_task is not None or not self.task_queue.empty()

    def get_current_task(self) -> Optional[str]:
        return self.current_task

task_manager = TaskManager()