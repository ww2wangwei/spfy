import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import json
import os
import sys
import subprocess
import time
import importlib
from pathlib import Path
from ..core import config_manager, task_manager
from ..tasks import (
    convert_mp4_to_mp3,
    convert_mp3_to_srt,
    remove_audio_from_mp4,
    convert_srt_to_mp3,
    merge_audio_video,
    burn_subtitle,
    proofread_srt,
    proofread_and_correct_srt,
    proofread_english_terms,
    translate_srt,
    translate_transcript_files
)
from ..core.translator_engine import translate_srt_strict_netflix
from ..utils import logger, open_file_explorer, clear_directory, get_dir_size
from ..core import TTSEngine

translator_engine = importlib.import_module('video_tool.core.translator_engine')

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("视频处理工具")
        self.root.geometry("1120x700")
        self.root.minsize(1000, 650)

        self.languages = ["中文(普通话)", "English", "Japanese", "Korean", "French", "German"]
        self.language_map = {"中文(普通话)": "Chinese", "English": "English", "Japanese": "Japanese",
                             "Korean": "Korean", "French": "French", "German": "German"}
        self.models = ["tiny", "base", "small", "medium", "large"]
        self.speeds = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
        self.translate_langs = ["English", "Japanese", "Korean", "French", "German", "Spanish", "Russian", "Portuguese", "Italian"]
        self.translate_lang_map = {
            "English": "en", "Japanese": "ja", "Korean": "ko", "French": "fr",
            "German": "de", "Spanish": "es", "Russian": "ru", "Portuguese": "pt", "Italian": "it"
        }
        self._load_model_settings()
        self.translation_models = list(translator_engine.TRANSLATION_MODELS.keys())
        self.selected_translation_model = tk.StringVar(value=translator_engine.get_translation_model())

        self.tts_engine = TTSEngine()
        self.voices = self.tts_engine.get_all_voices()

        self.selected_language = tk.StringVar(value="中文(普通话)")
        self.selected_model = tk.StringVar(value="small")
        self.selected_voice = tk.StringVar(value="en-US-JennyNeural")
        self.speed_align = tk.BooleanVar(value=True)
        self.max_speed = tk.DoubleVar(value=1.3)
        self.burn_acceleration = tk.BooleanVar(value=False)
        self.selected_translate_lang = tk.StringVar(value="English")
        self.player_video_path = tk.StringVar(value="")
        self.player_video_name = tk.StringVar(value="未选择视频")
        self.auto_play_burn_result = tk.BooleanVar(value=True)
        self.player_process = None
        self.player_window = None
        self.fullscreen_process = None
        self.fullscreen_window = None
        self.active_player_host = None
        self.player_title = "video_tool_embedded_player"
        self.player_duration = 0.0
        self.player_offset = 0.0
        self.player_started_at = None
        self.player_paused = False
        self.player_seeking = False
        self.player_progress_var = tk.DoubleVar(value=0.0)
        self.player_time_var = tk.StringVar(value="00:00 / 00:00")
        
        # 停止标志
        self._stop_requested = False
        self._current_thread = None
        
        self.create_menu()
        self.create_widgets()
        
        task_manager.start()
        task_manager.set_log_callback(self.add_log)
        task_manager.set_progress_callback(self.update_progress)
        
        self.update_voice_list()
        
        self.download_queue = queue.Queue()
        self.root.after(100, self.process_download_queue)
        self.root.after(500, self._update_player_progress)
    
    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="功能", menu=file_menu)
        
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="打开缓存目录", command=self.open_cache_dir)
        tools_menu.add_command(label="清空缓存", command=self.clear_cache)
        tools_menu.add_command(label="设置", command=self.show_settings)
        menubar.add_cascade(label="工具", menu=tools_menu)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self.show_about)
        help_menu.add_command(label="使用说明", command=self.show_help)
        menubar.add_cascade(label="帮助", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=5)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 参数配置区域 - 使用PanedWindow实现左右分栏
        param_frame = ttk.LabelFrame(main_frame, text="参数配置", padding=10)
        param_frame.pack(fill=tk.X, padx=5, pady=5)

        # 第一行：语言、模型、人声
        row1 = ttk.Frame(param_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="语言:").pack(side=tk.LEFT, padx=(0, 5))
        lang_combo = ttk.Combobox(row1, textvariable=self.selected_language,
                                  values=self.languages, state="readonly", width=14)
        lang_combo.pack(side=tk.LEFT, padx=(0, 15))
        lang_combo.bind("<<ComboboxSelected>>", self.on_language_change)

        ttk.Label(row1, text="识别模型:").pack(side=tk.LEFT, padx=(0, 5))
        model_combo = ttk.Combobox(row1, textvariable=self.selected_model,
                                    values=self.models, state="readonly", width=8)
        model_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="TTS人声:").pack(side=tk.LEFT, padx=(0, 5))
        self.voice_combo = ttk.Combobox(row1, textvariable=self.selected_voice,
                                         state="readonly", width=20)
        self.voice_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="翻译目标:").pack(side=tk.LEFT, padx=(0, 5))
        translate_lang_combo = ttk.Combobox(row1, textvariable=self.selected_translate_lang,
                                            values=self.translate_langs, state="readonly", width=10)
        translate_lang_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="翻译模型:").pack(side=tk.LEFT, padx=(0, 5))
        self.translate_model_combo = ttk.Combobox(row1, textvariable=self.selected_translation_model,
                                                  values=self.translation_models, state="readonly", width=18)
        self.translate_model_combo.pack(side=tk.LEFT)

        # 第二行：速度设置和功能按钮
        row2 = ttk.Frame(param_frame)
        row2.pack(fill=tk.X, pady=2)

        self.speed_align_check = ttk.Checkbutton(row2, text="变速对齐SRT时长",
                                                  variable=self.speed_align)
        self.speed_align_check.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(row2, text="最大语速:").pack(side=tk.LEFT, padx=(0, 5))
        speed_combo = ttk.Combobox(row2, textvariable=self.max_speed,
                                    values=self.speeds, state="readonly", width=6)
        speed_combo.pack(side=tk.LEFT, padx=(0, 15))

        self.burn_accel_check = ttk.Checkbutton(row2, text="烧录加速(硬件编码)",
                                                 variable=self.burn_acceleration)
        self.burn_accel_check.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(row2, text="打开缓存", command=self.open_cache_dir, width=10).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row2, text="清空缓存", command=self.clear_cache, width=10).pack(side=tk.LEFT)

        # 功能区域
        func_frame = ttk.LabelFrame(main_frame, text="功能", padding=10)
        func_frame.pack(fill=tk.X, padx=5, pady=5)

        func_content = ttk.Frame(func_frame)
        func_content.pack(fill=tk.X)

        button_frame = ttk.Frame(func_content)
        button_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        player_frame = ttk.LabelFrame(func_content, text="视频播放器", padding=8)
        player_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0))

        self.player_host = tk.Frame(
            player_frame,
            bg="#111111",
            width=320,
            height=190
        )
        self.player_host.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self.player_host.pack_propagate(False)
        self.player_host.bind("<Configure>", lambda _event: self._resize_embedded_player())
        self.active_player_host = self.player_host

        ttk.Label(player_frame, textvariable=self.player_video_name, width=32).pack(fill=tk.X, pady=(0, 6))

        progress_row = ttk.Frame(player_frame)
        progress_row.pack(fill=tk.X, pady=(0, 6))
        self.player_scale = ttk.Scale(
            progress_row,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.player_progress_var
        )
        self.player_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.player_scale.bind("<ButtonPress-1>", self._on_player_seek_start)
        self.player_scale.bind("<ButtonRelease-1>", self._on_player_seek_end)
        ttk.Label(progress_row, textvariable=self.player_time_var, width=15).pack(side=tk.LEFT)

        player_buttons = ttk.Frame(player_frame)
        player_buttons.pack(fill=tk.X)
        ttk.Button(player_buttons, text="选择视频", command=self.choose_player_video, width=9).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(player_buttons, text="暂停", command=self.pause_player_video, width=7).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(player_buttons, text="继续", command=self.resume_player_video, width=7).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(player_buttons, text="全屏", command=self.play_player_video_fullscreen, width=7).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(player_buttons, text="恢复", command=self.restore_player_window, width=7).pack(side=tk.LEFT)

        player_buttons2 = ttk.Frame(player_frame)
        player_buttons2.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(player_buttons2, text="打开目录", command=self.open_player_video_folder, width=9).pack(side=tk.LEFT)

        ttk.Checkbutton(
            player_frame,
            text="第9步完成后自动播放",
            variable=self.auto_play_burn_result
        ).pack(anchor=tk.W, pady=(6, 0))

        # 使用4列网格布局
        btn_specs = [
            ("① 批量 MP4 → MP3", 0, 0),
            ("② MP3 → 文字(SRT)", 0, 1),
            ("③ 字幕与逐字稿校对", 0, 2),
            ("④ 中文字幕翻译", 1, 0),
            ("⑤ 英文术语校对", 1, 1),
            ("⑥ SRT → MP3", 1, 2),
            ("⑦ MP4 去声音", 2, 0),
            ("⑧ 合并音视频(-new)", 2, 1),
            ("⑨ 烧录硬字幕(-sub)", 2, 2),
            ("⑩ 批量逐字稿翻译", 3, 0),
            ("⑪ 局部修正视频", 3, 1),
        ]

        for text, row, col in btn_specs:
            cmd_map = {
                "① 批量 MP4 → MP3": self.do_mp4_to_mp3,
                "② MP3 → 文字(SRT)": self.do_mp3_to_srt,
                "③ 字幕与逐字稿校对": self.do_proofread,
                "④ 中文字幕翻译": self.do_translate,
                "⑤ 英文术语校对": self.do_terminology_proofread,
                "⑥ SRT → MP3": self.do_srt_to_mp3,
                "⑦ MP4 去声音": self.do_mute_video,
                "⑧ 合并音视频(-new)": self.do_merge_av,
                "⑨ 烧录硬字幕(-sub)": self.do_burn_sub,
                "⑩ 批量逐字稿翻译": self.do_transcript_translate,
                "⑪ 局部修正视频": self.do_local_correction,
            }
            btn = ttk.Button(button_frame, text=text, command=cmd_map[text], width=22)
            btn.grid(row=row, column=col, padx=5, pady=5, sticky=tk.W)

        # 进度条区域
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, padx=5, pady=5)

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=5, pady=2)

        progress_info_frame = ttk.Frame(progress_frame)
        progress_info_frame.pack(fill=tk.X, padx=5)

        self.progress_label = ttk.Label(progress_info_frame, text="就绪")
        self.progress_label.pack(side=tk.LEFT)

        self.stop_button = ttk.Button(progress_info_frame, text="⏹ 停止", command=self.stop_task, width=10)
        self.stop_button.pack(side=tk.LEFT, padx=10)
        self.stop_button.config(state=tk.DISABLED)

        self.cache_size_label = ttk.Label(progress_info_frame, text=f"缓存大小: {get_dir_size(str(config_manager.get_cache_dir()))}")
        self.cache_size_label.pack(side=tk.RIGHT)

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="日志")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_inner, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9))
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_scrollbar = ttk.Scrollbar(log_inner, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=self.log_scrollbar.set)
    
    def on_language_change(self, event):
        self.update_voice_list()

    def update_voice_list(self):
        lang_display = self.selected_language.get()
        lang_key = self.language_map.get(lang_display, "Chinese")
        voice_list = self.voices.get(lang_key, [])

        # 获取所有可用语音作为备选（当特定语言为空时）
        all_voices = []
        for vlist in self.voices.values():
            all_voices.extend(vlist)

        # 设置语音列表：优先使用当前语言的，如果没有则显示所有语音
        if voice_list:
            self.voice_combo['values'] = voice_list
            # 如果当前选择的语音不在列表中，保留选择（尝试匹配）
            current = self.selected_voice.get()
            if current not in voice_list:
                # 查找是否在所有语音中
                if current in all_voices:
                    pass  # 保留当前选择
                else:
                    self.selected_voice.set(voice_list[0])
        else:
            # 该语言没有特定语音，显示所有语音
            self.voice_combo['values'] = all_voices
            if self.selected_voice.get() not in all_voices:
                self.selected_voice.set(all_voices[0] if all_voices else "")

    def _load_model_settings(self):
        """从设置文件加载大模型配置并应用到全局翻译配置"""
        config_file = str(config_manager.get_model_settings_path())
        legacy_config_file = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "model_settings.json")
        )
        if not os.path.exists(config_file) and os.path.exists(legacy_config_file):
            config_file = legacy_config_file
        if not os.path.exists(config_file):
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            translator_engine.update_translation_config(
                api_key=settings.get("api_key", translator_engine.MINIMAX_API_KEY),
                api_url=settings.get("api_url", translator_engine.MINIMAX_BASE_URL),
                models=settings.get("models", translator_engine.TRANSLATION_MODELS),
                current_model=settings.get("current_model", translator_engine.get_translation_model())
            )
        except Exception as e:
            print(f"加载大模型设置失败: {str(e)}")

    def _refresh_model_selector(self):
        """刷新主界面大模型下拉框"""
        self.translation_models = list(translator_engine.TRANSLATION_MODELS.keys())
        self.translate_model_combo['values'] = self.translation_models
        current_model = translator_engine.get_translation_model()
        if current_model in self.translation_models:
            self.selected_translation_model.set(current_model)
        elif self.translation_models:
            self.selected_translation_model.set(self.translation_models[0])
    
    def add_log(self, message):
        self.download_queue.put(('log', message))
    
    def update_progress(self, current, total, message):
        self.download_queue.put(('progress', current, total, message))
    
    def process_download_queue(self):
        while not self.download_queue.empty():
            item = self.download_queue.get()
            if item[0] == 'log':
                self._add_log_safe(item[1])
            elif item[0] == 'progress':
                self._update_progress_safe(item[1], item[2], item[3])
        self.root.after(100, self.process_download_queue)
    
    def _add_log_safe(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def _update_progress_safe(self, current, total, message):
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_var.set(percentage)
            self.progress_label.config(text=f"{message} ({percentage}%)")
        else:
            self.progress_var.set(0)
            self.progress_label.config(text=message)
    
    def reset_progress(self):
        self.download_queue.put(('progress_reset',))
    
    def _reset_progress_safe(self):
        self.progress_var.set(0)
        self.progress_label.config(text="就绪")
        self.stop_button.config(state=tk.DISABLED)  # 禁用停止按钮
        self._stop_requested = False  # 重置停止标志

    def choose_player_video(self):
        """选择一个视频放入右侧播放器面板"""
        file = filedialog.askopenfilename(
            title="选择要播放的视频",
            filetypes=[("视频文件", "*.mp4;*.mov;*.mkv;*.avi"), ("所有文件", "*.*")]
        )
        if file:
            self.set_player_video(file)
            self.play_player_video()

    def set_player_video(self, video_path):
        """设置播放器当前视频"""
        path = Path(video_path)
        self.player_video_path.set(str(path))
        self.player_video_name.set(path.name if path.name else "未选择视频")
        self.player_duration = self._get_video_duration(str(path))
        self.player_offset = 0.0
        self.player_started_at = None
        self.player_paused = False
        self.player_progress_var.set(0.0)
        self._update_player_time_label(0.0)
        self.add_log(f"播放器: 当前视频 {path}")

    def play_player_video(self):
        """在右侧播放器区域播放当前视频"""
        video_path = self.player_video_path.get().strip()
        if not video_path:
            messagebox.showwarning("提示", "请先选择要播放的视频")
            return
        if not os.path.exists(video_path):
            messagebox.showwarning("提示", "视频文件不存在")
            return
        try:
            if not self._play_in_embedded_window(video_path, start_time=self.player_offset, host=self.player_host):
                self._open_path(video_path)
        except Exception as e:
            messagebox.showerror("错误", f"播放视频失败: {str(e)}")

    def stop_embedded_player(self):
        """停止右侧内嵌播放器"""
        self._stop_player_processes()
        self.player_offset = 0.0
        self.player_started_at = None
        self.player_paused = False
        self.player_progress_var.set(0.0)
        self._update_player_time_label(0.0)

    def _stop_player_processes(self):
        if self.player_process and self.player_process.poll() is None:
            try:
                self.player_process.terminate()
            except Exception:
                pass
        if self.fullscreen_process and self.fullscreen_process.poll() is None:
            try:
                self.fullscreen_process.terminate()
            except Exception:
                pass
        self.player_process = None
        self.player_window = None
        self.fullscreen_process = None
        self.active_player_host = self.player_host

    def pause_player_video(self):
        """暂停当前视频"""
        if self.player_paused:
            return
        if self.player_process and self.player_process.poll() is None:
            host = self.active_player_host
            self.player_offset = self._current_player_position()
            self._stop_player_processes()
            self.active_player_host = host or self.player_host
            self.player_started_at = None
            self.player_paused = True
            self.player_progress_var.set(self.player_offset)
            self._update_player_time_label(self.player_offset)
            self.add_log(f"播放器: 已暂停在 {self._format_seconds(self.player_offset)}")

    def resume_player_video(self):
        """继续播放当前视频"""
        video_path = self.player_video_path.get().strip()
        if not video_path:
            messagebox.showwarning("提示", "请先选择要播放的视频")
            return
        if self.player_paused:
            self._play_in_embedded_window(
                video_path,
                start_time=self.player_offset,
                host=self.active_player_host or self.player_host
            )
            self.add_log(f"播放器: 从 {self._format_seconds(self.player_offset)} 继续播放")
            return
        self.play_player_video()

    def _send_player_key(self, key):
        if not self.player_window or sys.platform != "win32":
            return
        try:
            import win32api
            import win32con
            import win32gui

            vk = win32api.VkKeyScan(key) & 0xff
            win32gui.PostMessage(self.player_window, win32con.WM_KEYDOWN, vk, 0)
            win32gui.PostMessage(self.player_window, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            self.add_log(f"播放器: 暂停/继续控制失败: {str(e)}")

    def play_player_video_fullscreen(self):
        """打开带控制栏的全屏播放窗口"""
        video_path = self.player_video_path.get().strip()
        if not video_path:
            messagebox.showwarning("提示", "请先选择要播放的视频")
            return
        if not os.path.exists(video_path):
            messagebox.showwarning("提示", "视频文件不存在")
            return

        start_time = self._current_player_position()
        self._stop_player_processes()
        if self.fullscreen_window and self.fullscreen_window.winfo_exists():
            self.fullscreen_window.destroy()

        win = tk.Toplevel(self.root)
        win.title("全屏播放器")
        win.attributes("-fullscreen", True)
        win.configure(bg="#111111")
        win.protocol("WM_DELETE_WINDOW", self.restore_player_window)
        win.bind("<Escape>", lambda _event: self.restore_player_window())
        self.fullscreen_window = win

        video_host = tk.Frame(win, bg="#111111")
        video_host.pack(fill=tk.BOTH, expand=True)
        video_host.bind("<Configure>", lambda _event: self._resize_embedded_player())

        controls = ttk.Frame(win, padding=8)
        controls.pack(fill=tk.X)

        full_scale = ttk.Scale(
            controls,
            from_=0,
            to=max(1.0, self.player_duration),
            orient=tk.HORIZONTAL,
            variable=self.player_progress_var
        )
        full_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        full_scale.bind("<ButtonPress-1>", self._on_player_seek_start)
        full_scale.bind("<ButtonRelease-1>", self._on_player_seek_end)
        ttk.Label(controls, textvariable=self.player_time_var, width=15).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(controls, text="暂停", command=self.pause_player_video, width=7).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(controls, text="继续", command=self.resume_player_video, width=7).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(controls, text="恢复窗口", command=self.restore_player_window, width=10).pack(side=tk.LEFT)

        self._play_in_embedded_window(video_path, start_time=start_time, host=video_host)
        self.add_log(f"播放器: 全屏播放 {video_path}")

    def restore_player_window(self):
        """关闭全屏播放并恢复右侧窗口播放"""
        if self.fullscreen_process and self.fullscreen_process.poll() is None:
            try:
                self.fullscreen_process.terminate()
            except Exception:
                pass
        self.fullscreen_process = None
        video_path = self.player_video_path.get().strip()
        if self.fullscreen_window and self.fullscreen_window.winfo_exists():
            self.fullscreen_window.destroy()
        self.fullscreen_window = None
        if video_path and os.path.exists(video_path):
            self.player_offset = self._current_player_position()
            self._play_in_embedded_window(video_path, start_time=self.player_offset, host=self.player_host)

    def _play_in_embedded_window(self, video_path, start_time=0.0, host=None):
        ffplay_path = self._get_ffplay_path()
        if not ffplay_path:
            self.add_log("播放器: 未找到 ffplay，改用系统默认播放器")
            return False

        self._stop_player_processes()
        host = host or self.player_host
        self.active_player_host = host
        host.update_idletasks()
        width = max(240, host.winfo_width())
        height = max(120, host.winfo_height())
        title = f"{self.player_title}_{os.getpid()}"
        self.player_title = title

        cmd = [
            ffplay_path,
            "-window_title", title,
            "-x", str(width),
            "-y", str(height),
            "-autoexit",
            "-loglevel", "quiet",
            "-ss", f"{max(0.0, float(start_time)):.3f}",
            video_path
        ]
        self.player_process = subprocess.Popen(cmd)
        self.player_offset = max(0.0, float(start_time))
        self.player_started_at = time.monotonic()
        self.player_paused = False
        self.root.after(300, lambda: self._embed_ffplay_window(title, host, attempts=20))
        self.add_log(f"播放器: 正在窗口内播放 {video_path}")
        return True

    def _get_ffplay_path(self):
        ffmpeg_path = config_manager.get_ffmpeg_path()
        candidates = []
        if ffmpeg_path and ffmpeg_path != "ffmpeg":
            ffmpeg_file = Path(ffmpeg_path)
            candidates.append(str(ffmpeg_file.with_name("ffplay.exe")))
        candidates.append("ffplay")

        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if result.returncode == 0:
                    return candidate
            except Exception:
                continue
        return None

    def _get_ffprobe_path(self):
        ffmpeg_path = config_manager.get_ffmpeg_path()
        candidates = []
        if ffmpeg_path and ffmpeg_path != "ffmpeg":
            ffmpeg_file = Path(ffmpeg_path)
            candidates.append(str(ffmpeg_file.with_name("ffprobe.exe")))
        candidates.append("ffprobe")
        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if result.returncode == 0:
                    return candidate
            except Exception:
                continue
        return None

    def _get_video_duration(self, video_path):
        ffprobe_path = self._get_ffprobe_path()
        if not ffprobe_path:
            return 0.0
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=nokey=1:noprint_wrappers=1",
                    video_path
                ],
                capture_output=True,
                text=True,
                timeout=8
            )
            if result.returncode == 0 and result.stdout.strip():
                return max(0.0, float(result.stdout.strip()))
        except Exception:
            pass
        return 0.0

    def _current_player_position(self):
        if self.player_started_at is None or self.player_paused:
            pos = self.player_offset
        else:
            pos = self.player_offset + (time.monotonic() - self.player_started_at)
        if self.player_duration > 0:
            pos = min(pos, self.player_duration)
        return max(0.0, pos)

    def _update_player_progress(self):
        if not self.player_seeking:
            pos = self._current_player_position()
            if self.player_duration > 0:
                self.player_progress_var.set(pos)
                self.player_scale.configure(to=self.player_duration)
            else:
                self.player_progress_var.set(0.0)
            self._update_player_time_label(pos)
        self.root.after(500, self._update_player_progress)

    def _update_player_time_label(self, pos):
        self.player_time_var.set(f"{self._format_seconds(pos)} / {self._format_seconds(self.player_duration)}")

    def _format_seconds(self, seconds):
        seconds = max(0, int(seconds or 0))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_player_seek_start(self, _event=None):
        self.player_seeking = True

    def _on_player_seek_end(self, _event=None):
        self.player_seeking = False
        target = float(self.player_progress_var.get())
        self.seek_player_video(target)

    def seek_player_video(self, target):
        video_path = self.player_video_path.get().strip()
        if not video_path or not os.path.exists(video_path):
            return
        self.player_offset = max(0.0, min(float(target), self.player_duration if self.player_duration > 0 else float(target)))
        self._update_player_time_label(self.player_offset)
        self._play_in_embedded_window(video_path, start_time=self.player_offset, host=self.active_player_host or self.player_host)

    def _embed_ffplay_window(self, title, host, attempts=20):
        if not self.player_process or self.player_process.poll() is not None:
            return
        if sys.platform != "win32":
            return
        try:
            import win32con
            import win32gui

            hwnd = self._find_window_by_title(title)
            if not hwnd:
                if attempts > 0:
                    self.root.after(250, lambda: self._embed_ffplay_window(title, host, attempts - 1))
                return

            host_hwnd = host.winfo_id()
            win32gui.SetParent(hwnd, host_hwnd)
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            style = style & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_POPUP
            style = style | win32con.WS_CHILD | win32con.WS_VISIBLE
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
            self.player_window = hwnd
            self.active_player_host = host
            self._resize_embedded_player()
        except Exception as e:
            self.add_log(f"播放器: 内嵌播放失败，保留独立窗口: {str(e)}")

    def _find_window_by_title(self, title):
        import win32gui

        matched = []

        def enum_handler(hwnd, _ctx):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
                matched.append(hwnd)

        win32gui.EnumWindows(enum_handler, None)
        return matched[0] if matched else None

    def _resize_embedded_player(self):
        if not self.player_window or sys.platform != "win32":
            return
        try:
            import win32gui
            host = self.active_player_host or self.player_host
            width = max(1, host.winfo_width())
            height = max(1, host.winfo_height())
            win32gui.MoveWindow(self.player_window, 0, 0, width, height, True)
        except Exception:
            pass

    def open_player_video_folder(self):
        """打开当前视频所在目录"""
        video_path = self.player_video_path.get().strip()
        if not video_path:
            messagebox.showwarning("提示", "请先选择要播放的视频")
            return
        folder = str(Path(video_path).parent)
        if os.path.exists(folder):
            open_file_explorer(folder)

    def _open_path(self, path):
        if hasattr(os, "startfile"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _get_burn_output_path(self, video_file):
        video_path = Path(video_file)
        base_name = video_path.stem
        if base_name.endswith('-new'):
            base_name = base_name[:-4]
        return video_path.parent / f"{base_name}_final.mp4"
    
    def stop_task(self):
        """强制停止当前任务"""
        if messagebox.askyesno("确认", "确定要停止当前任务吗？"):
            task_manager.request_stop()
            self.add_log("⚠ 用户请求停止任务...")
            self.progress_label.config(text="正在停止...")
            self.stop_button.config(state=tk.DISABLED)
    
    def _start_task(self):
        """任务开始时调用"""
        self._stop_requested = False
        self.stop_button.config(state=tk.NORMAL)  # 启用停止按钮
    
    def _check_stop(self) -> bool:
        """检查是否请求停止"""
        return self._stop_requested
    
    def do_mp4_to_mp3(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        files = filedialog.askopenfilenames(filetypes=[("MP4文件", "*.mp4")])
        if not files:
            return
        
        def run_task():
            try:
                convert_mp4_to_mp3(
                    list(files),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def do_mp3_to_srt(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        file = filedialog.askopenfilename(filetypes=[("MP3文件", "*.mp3")])
        if not file:
            return
        
        lang_key = self.language_map.get(self.selected_language.get(), "Chinese")
        
        # 只有中文才需要繁体转简体
        convert_to_simplified = (lang_key == "Chinese")
        
        # 弹出对话框询问前置时间
        lead_time = self._ask_lead_time()
        if lead_time is None:
            return  # 用户取消
        
        def run_task():
            try:
                convert_mp3_to_srt(
                    file,
                    language=lang_key,
                    model_name=self.selected_model.get(),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log,
                    convert_to_simplified=convert_to_simplified,
                    lead_time=lead_time
                )
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def _ask_lead_time(self):
        """弹出对话框询问前置时间"""
        dialog = tk.Toplevel(self.root)
        dialog.title("设置前置时间")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.geometry("350x150")
        dialog_x = self.root.winfo_x() + (self.root.winfo_width() - 350) // 2
        dialog_y = self.root.winfo_y() + (self.root.winfo_height() - 150) // 2
        dialog.geometry(f"+{dialog_x}+{dialog_y}")
        
        result = [0.0]  # 默认值
        cancelled = [False]
        
        ttk.Label(dialog, text="字幕时间轴手动偏移（秒）：").pack(pady=10)
        ttk.Label(dialog, text="（通常保持0；正数会让字幕整体延后）").pack()
        
        time_var = tk.StringVar(value="0")
        entry = ttk.Entry(dialog, textvariable=time_var, width=15)
        entry.pack(pady=10)
        entry.select_range(0, tk.END)
        entry.focus_set()
        
        def on_ok(event=None):
            try:
                result[0] = float(time_var.get())
            except ValueError:
                result[0] = 0.0
            dialog.destroy()
        
        def on_cancel():
            cancelled[0] = True
            dialog.destroy()
        
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=on_ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=10).pack(side=tk.LEFT, padx=5)
        
        dialog.bind('<Return>', on_ok)
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        dialog.wait_window()
        
        return None if cancelled[0] else result[0]
    
    def _ask_speed_multiplier(self):
        """弹出对话框询问字幕时间轴倍数"""
        dialog = tk.Toplevel(self.root)
        dialog.title("设置字幕时间轴倍数")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.geometry("400x220")
        dialog_x = self.root.winfo_x() + (self.root.winfo_width() - 400) // 2
        dialog_y = self.root.winfo_y() + (self.root.winfo_height() - 220) // 2
        dialog.geometry(f"+{dialog_x}+{dialog_y}")
        
        result = [1.0]  # 默认值
        cancelled = [False]
        
        ttk.Label(dialog, text="调整字幕时间轴倍数（影响语音速度）：").pack(pady=5)
        ttk.Label(dialog, text="（1.0=正常速度，小于1减慢，大于1加快）").pack()
        
        speed_var = tk.StringVar(value="1.0")
        entry = ttk.Entry(dialog, textvariable=speed_var, width=15)
        entry.pack(pady=10)
        entry.select_range(0, tk.END)
        entry.focus_set()
        
        # 快捷按钮
        speed_buttons = ["0.8", "0.85", "0.9", "0.95", "1.0", "1.1", "1.2"]
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=5)
        
        for speed in speed_buttons:
            ttk.Button(btn_frame, text=speed, 
                       command=lambda s=speed: speed_var.set(s), width=6).pack(side=tk.LEFT, padx=2)
        
        def on_ok(event=None):
            try:
                val = float(speed_var.get())
                # 限制范围
                if val < 0.5:
                    val = 0.5
                elif val > 2.0:
                    val = 2.0
                result[0] = val
            except ValueError:
                result[0] = 1.0
            dialog.destroy()
        
        def on_cancel():
            cancelled[0] = True
            dialog.destroy()
        
        btn_frame2 = ttk.Frame(dialog)
        btn_frame2.pack(pady=10)
        ttk.Button(btn_frame2, text="确定", command=on_ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame2, text="取消", command=on_cancel, width=10).pack(side=tk.LEFT, padx=5)
        
        dialog.bind('<Return>', on_ok)
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        dialog.wait_window()
        
        return None if cancelled[0] else result[0]
    
    def do_mute_video(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        files = filedialog.askopenfilenames(filetypes=[("MP4文件", "*.mp4")])
        if not files:
            return
        
        def run_task():
            try:
                remove_audio_from_mp4(
                    list(files),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def do_srt_to_mp3(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        file = filedialog.askopenfilename(filetypes=[("SRT文件", "*.srt")])
        if not file:
            return
        
        def run_task():
            self._start_task()
            try:
                convert_srt_to_mp3(
                    file,
                    voice=self.selected_voice.get(),
                    speed_align=self.speed_align.get(),
                    max_speed=self.max_speed.get(),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def do_merge_av(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        # 选择视频文件
        video_file = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("MP4文件", "*.mp4"), ("所有视频", "*.mkv;*.mov;*.avi")]
        )
        if not video_file:
            return
        
        # 选择音频文件
        audio_file = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=[("MP3文件", "*.mp3"), ("所有音频", "*.wav;*.flac;*.aac")]
        )
        if not audio_file:
            return
        
        def run_task():
            try:
                merge_audio_video(
                    video_file,
                    audio_file,
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def do_burn_sub(self):
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        # 选择视频文件
        video_file = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[("MP4文件", "*.mp4"), ("所有视频", "*.mkv;*.mov;*.avi")]
        )
        if not video_file:
            return
        
        # 选择字幕文件
        srt_file = filedialog.askopenfilename(
            title="选择字幕文件",
            filetypes=[("SRT文件", "*.srt"), ("ASS文件", "*.ass"), ("SSA文件", "*.ssa")]
        )
        if not srt_file:
            return
        
        def run_task():
            try:
                success_count, _fail_count = burn_subtitle(
                    video_file,
                    srt_file,
                    use_hardware_accel=self.burn_acceleration.get(),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
                output_path = self._get_burn_output_path(video_file)
                if success_count > 0 and output_path.exists():
                    def update_player():
                        self.set_player_video(str(output_path))
                        if self.auto_play_burn_result.get():
                            self.play_player_video()
                    self.root.after(0, update_player)
            finally:
                self._reset_progress_safe()
        
        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()
    
    def do_proofread(self):
        """校对字幕与逐字稿"""
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return
        
        # 先选择字幕文件
        srt_file = filedialog.askopenfilename(
            title="选择字幕文件",
            filetypes=[("SRT字幕文件", "*.srt"), ("所有文件", "*.*")]
        )
        if not srt_file:
            return
        
        # 再选择逐字稿文件
        txt_file = filedialog.askopenfilename(
            title="选择逐字稿文件",
            filetypes=[("Word文档", "*.docx;*.doc"), ("Word 2007+", "*.docx"), ("Word 97-2003", "*.doc"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if not txt_file:
            return

        translator_engine.set_translation_model(self.selected_translation_model.get())
        self.add_log(f"字幕校对模型: {self.selected_translation_model.get()}")
        
        def run_task():
            try:
                proofread_and_correct_srt(
                    srt_path=srt_file,
                    transcript_path=txt_file,
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            except Exception as e:
                self.add_log(f"✗ 字幕与逐字稿校对失败: {str(e)}")
            finally:
                self._reset_progress_safe()

        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()

    def do_terminology_proofread(self):
        """校对英文字幕专业术语"""
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return

        srt_file = filedialog.askopenfilename(
            title="选择英文字幕文件",
            filetypes=[("SRT字幕文件", "*.srt"), ("所有文件", "*.*")]
        )
        if not srt_file:
            return

        options = self._ask_terminology_options()
        if options is None:
            return

        domain, glossary_path = options
        translator_engine.set_translation_model(self.selected_translation_model.get())
        self.add_log(f"术语校对模型: {self.selected_translation_model.get()}")

        def run_task():
            self._start_task()
            try:
                proofread_english_terms(
                    srt_path=srt_file,
                    domain=domain,
                    glossary_path=glossary_path,
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            except Exception as e:
                self.add_log(f"✗ 英文术语校对失败: {str(e)}")
            finally:
                self._reset_progress_safe()

        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()

    def _ask_terminology_options(self):
        """弹出英文术语校对参数窗口"""
        dialog = tk.Toplevel(self.root)
        dialog.title("英文术语校对")
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.geometry("520x220")
        dialog_x = self.root.winfo_x() + (self.root.winfo_width() - 520) // 2
        dialog_y = self.root.winfo_y() + (self.root.winfo_height() - 220) // 2
        dialog.geometry(f"+{dialog_x}+{dialog_y}")

        domain_var = tk.StringVar(value="机床电气控制")
        glossary_var = tk.StringVar(value="")
        result = {'value': None}

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="专业方向:").grid(row=0, column=0, sticky=tk.W, pady=6)
        domain_entry = ttk.Entry(frame, textvariable=domain_var, width=48)
        domain_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=6)

        ttk.Label(frame, text="术语词库:").grid(row=1, column=0, sticky=tk.W, pady=6)
        glossary_entry = ttk.Entry(frame, textvariable=glossary_var, width=40)
        glossary_entry.grid(row=1, column=1, sticky=tk.EW, pady=6)

        def choose_glossary():
            path = filedialog.askopenfilename(
                title="选择术语词库文档",
                filetypes=[
                    ("术语词库", "*.txt;*.csv;*.docx"),
                    ("文本文件", "*.txt"),
                    ("CSV文件", "*.csv"),
                    ("Word文档", "*.docx"),
                    ("所有文件", "*.*")
                ]
            )
            if path:
                glossary_var.set(path)

        ttk.Button(frame, text="选择", command=choose_glossary, width=8).grid(row=1, column=2, padx=(6, 0), pady=6)

        ttk.Label(
            frame,
            text="词库格式示例：砂轮 = grinding wheel；或 CSV 两列：原术语,标准术语"
        ).grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=6)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=1, columnspan=2, sticky=tk.E, pady=18)

        def on_ok(event=None):
            domain = domain_var.get().strip()
            glossary_path = glossary_var.get().strip() or None
            if not domain and not glossary_path:
                messagebox.showwarning("提示", "请填写专业方向，或选择术语词库")
                return
            result['value'] = (domain, glossary_path)
            dialog.destroy()

        def on_cancel():
            result['value'] = None
            dialog.destroy()

        ttk.Button(btn_frame, text="开始校对", command=on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=10).pack(side=tk.LEFT, padx=5)

        frame.columnconfigure(1, weight=1)
        domain_entry.focus_set()
        dialog.bind('<Return>', on_ok)
        dialog.bind('<Escape>', lambda e: on_cancel())
        dialog.wait_window()

        return result['value']

    def do_translate(self):
        """翻译中文字幕（使用SRT时间戳）"""
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return

        # 选择中文字幕文件
        srt_file = filedialog.askopenfilename(
            title="选择中文字幕文件",
            filetypes=[("SRT字幕文件", "*.srt"), ("所有文件", "*.*")]
        )
        if not srt_file:
            return

        # 获取目标语言
        target_lang_display = self.selected_translate_lang.get()
        target_lang = self.translate_lang_map.get(target_lang_display, "en")

        # 设置翻译模型
        from ..core.translator_engine import set_translation_model
        selected_model = self.selected_translation_model.get()
        set_translation_model(selected_model)
        self.add_log(f"翻译模型: {selected_model}")

        def run_task():
            self._start_task()
            try:
                translate_srt_strict_netflix(
                    srt_path=srt_file,
                    target_lang=target_lang,
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            finally:
                self._reset_progress_safe()

        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()

    def do_transcript_translate(self):
        """批量翻译逐字稿文档"""
        if task_manager.is_busy():
            messagebox.showwarning("提示", "请等待当前任务完成")
            return

        files = filedialog.askopenfilenames(
            title="选择逐字稿文件",
            filetypes=[
                ("逐字稿文件", "*.doc;*.docx;*.txt;*.md;*.srt;*.csv"),
                ("Word文档", "*.doc;*.docx"),
                ("文本文件", "*.txt"),
                ("Markdown文件", "*.md"),
                ("SRT文件", "*.srt"),
                ("CSV文件", "*.csv"),
                ("所有文件", "*.*")
            ]
        )
        if not files:
            return

        translator_engine.set_translation_model(self.selected_translation_model.get())
        self.add_log(f"逐字稿翻译模型: {self.selected_translation_model.get()}")

        def run_task():
            self._start_task()
            try:
                translate_transcript_files(
                    list(files),
                    progress_callback=self.update_progress,
                    log_callback=self.add_log
                )
            except Exception as e:
                self.add_log(f"✗ 批量逐字稿翻译失败: {str(e)}")
            finally:
                self._reset_progress_safe()

        self._start_task()
        threading.Thread(target=run_task, daemon=True).start()

    def do_local_correction(self):
        """打开局部修正工作台"""
        from .local_correction_window import LocalCorrectionWindow
        LocalCorrectionWindow(
            self.root,
            voice_getter=lambda: self.selected_voice.get(),
            hardware_accel_getter=lambda: self.burn_acceleration.get(),
            log_callback=self.add_log,
            progress_callback=self.update_progress
        )

    def open_cache_dir(self):
        cache_dir = str(config_manager.get_cache_dir())
        open_file_explorer(cache_dir)    
    def clear_cache(self):
        if messagebox.askyesno("确认", "确定要清空缓存吗？这将删除所有下载的模型文件。"):
            cache_dir = str(config_manager.get_cache_dir())
            clear_directory(cache_dir)
            self.cache_size_label.config(text=f"缓存大小: {get_dir_size(cache_dir)}")
            self.add_log("缓存已清空")
    
    def show_settings(self):
        """显示大模型设置窗口"""
        from .settings_window import ModelSettingsWindow
        settings_window = ModelSettingsWindow(self.root)
        self.root.wait_window(settings_window.window)
        self._load_model_settings()
        self._refresh_model_selector()
    
    def show_about(self):
        messagebox.showinfo("关于", "视频处理工具 v1.0\n\n一站式视频处理解决方案")
    
    def show_help(self):
        help_text = """使用说明：

1. 批量 MP4 → MP3：选择一个或多个MP4文件，提取音频保存为MP3

2. MP3 → 文字 (SRT)：选择MP3文件，使用Whisper识别为SRT字幕

3. 字幕与逐字稿校对：选择SRT字幕文件和TXT逐字稿，进行对比分析

4. 中文字幕翻译：选择中文字幕文件，翻译为英文或其他语言

5. 英文术语校对：按专业方向或词库校对英文字幕术语

6. SRT → MP3：选择SRT文件，使用TTS转换为语音

7. MP4 去声音：选择MP4文件，移除音频轨道生成静音视频

8. 合并音视频：选择目录，自动匹配-mute.mp4和.mp3文件合并

9. 烧录硬字幕：选择目录，自动匹配-new.mp4和.srt文件烧录

10. 批量逐字稿翻译：选择逐字稿文件，翻译为中英表格Word

11. 局部修正视频：按SRT段落快速修改字幕、导出单段配音、重新烧录视频

工作流程示例：
MP4 → 去声音 → MP3 → 识别 → SRT → 翻译 → TTS → 合并 → 烧录
"""
        messagebox.showinfo("使用说明", help_text)
    
    def on_closing(self):
        self.stop_embedded_player()
        task_manager.stop()
        self.root.destroy()
