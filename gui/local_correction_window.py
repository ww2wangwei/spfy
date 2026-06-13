"""
局部修正窗口：按 SRT 段落快速修改字幕，并可重新烧录视频或导出单段配音。
"""
import asyncio
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from ..core.srt_parser import SRTParser
from ..core import TTSEngine, FFmpegExecutor, config_manager


class LocalCorrectionWindow:
    def __init__(self, parent, voice_getter, hardware_accel_getter, log_callback, progress_callback):
        self.window = tk.Toplevel(parent)
        self.window.title("局部修正视频")
        self.window.geometry("1100x720")
        self.window.minsize(980, 640)
        self.window.configure(bg="#eef2f7")
        self.window.transient(parent)

        self.voice_getter = voice_getter
        self.hardware_accel_getter = hardware_accel_getter
        self.log_callback = log_callback
        self.progress_callback = progress_callback

        self.parser = SRTParser()
        self.items = []
        self.srt_path = None
        self.video_path = None
        self.saved_srt_path = None
        self.tts_engine = TTSEngine()
        self.original_texts = {}
        self.modified_indices = set()
        self.current_index = None

        self.srt_var = tk.StringVar()
        self.video_var = tk.StringVar()
        self.segment_var = tk.StringVar(value="未选择段落")
        self.modified_var = tk.StringVar(value="已修改 0 段")
        self.segment_search_var = tk.StringVar()
        self.time_search_var = tk.StringVar()
        self.content_search_var = tk.StringVar()
        self.search_status_var = tk.StringVar(value="")
        self.search_results = []
        self.search_pos = -1
        self.last_search_keyword = ""
        self.last_search_mode = ""

        self._create_widgets()

    def _create_widgets(self):
        root = ttk.Frame(self.window, padding=(14, 12), style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        file_frame = ttk.LabelFrame(root, text="文件", padding=(12, 10), style="Card.TLabelframe")
        file_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(file_frame, text="SRT字幕:").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=4)
        ttk.Entry(file_frame, textvariable=self.srt_var).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Button(file_frame, text="选择", command=self._choose_srt, width=8).grid(row=0, column=2, padx=6)
        ttk.Button(file_frame, text="加载", command=self._load_srt, width=8).grid(row=0, column=3)

        ttk.Label(file_frame, text="源视频(-new.mp4):").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=4)
        ttk.Entry(file_frame, textvariable=self.video_var).grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Button(file_frame, text="选择", command=self._choose_video, width=8).grid(row=1, column=2, padx=6)
        file_frame.columnconfigure(1, weight=1)

        body = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, pady=10)

        list_frame = ttk.Frame(body)
        body.add(list_frame, weight=3)

        search_frame = ttk.Frame(list_frame, style="App.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 6))
        search_row1 = ttk.Frame(search_frame, style="App.TFrame")
        search_row1.pack(fill=tk.X, pady=(0, 4))
        search_row2 = ttk.Frame(search_frame, style="App.TFrame")
        search_row2.pack(fill=tk.X)

        ttk.Label(search_row1, text="段号:").pack(side=tk.LEFT, padx=(0, 4))
        segment_entry = ttk.Entry(search_row1, textvariable=self.segment_search_var, width=8)
        segment_entry.pack(side=tk.LEFT, padx=(0, 6))
        segment_entry.bind("<Return>", lambda _event: self._search("segment"))
        segment_entry.bind("<KeyRelease>", self._on_search_changed)
        ttk.Button(search_row1, text="找段号", command=lambda: self._search("segment"), width=7).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(search_row1, text="时间:").pack(side=tk.LEFT, padx=(0, 4))
        time_entry = ttk.Entry(search_row1, textvariable=self.time_search_var, width=14)
        time_entry.pack(side=tk.LEFT, padx=(0, 6))
        time_entry.bind("<Return>", lambda _event: self._search("time"))
        time_entry.bind("<KeyRelease>", self._on_search_changed)
        ttk.Button(search_row1, text="找时间", command=lambda: self._search("time"), width=7).pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(search_row2, text="内容:").pack(side=tk.LEFT, padx=(0, 4))
        content_entry = ttk.Entry(search_row2, textvariable=self.content_search_var)
        content_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        content_entry.bind("<Return>", lambda _event: self._search("content"))
        content_entry.bind("<KeyRelease>", self._on_search_changed)
        ttk.Button(search_row2, text="找内容", command=lambda: self._search("content"), width=7).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(search_row2, text="上一个", command=self._search_prev, width=7).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(search_row2, text="下一个", command=self._search_next, width=7).pack(side=tk.LEFT)
        ttk.Label(search_row2, textvariable=self.search_status_var, width=8).pack(side=tk.LEFT, padx=(8, 0))

        tree_frame = ttk.Frame(list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("index", "status", "time", "text")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("index", text="段号")
        self.tree.heading("status", text="状态")
        self.tree.heading("time", text="时间")
        self.tree.heading("text", text="字幕内容")
        self.tree.column("index", width=60, anchor=tk.CENTER)
        self.tree.column("status", width=70, anchor=tk.CENTER)
        self.tree.column("time", width=210, anchor=tk.CENTER)
        self.tree.column("text", width=520, anchor=tk.W)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        y_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        y_scrollbar.grid(row=0, column=1, sticky=tk.NS)
        x_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        x_scrollbar.grid(row=1, column=0, sticky=tk.EW)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)

        edit_frame = ttk.LabelFrame(body, text="当前段落", padding=(12, 10), style="Card.TLabelframe")
        body.add(edit_frame, weight=2)

        ttk.Label(edit_frame, textvariable=self.segment_var).pack(anchor=tk.W)
        self.text_box = tk.Text(
            edit_frame,
            height=10,
            wrap=tk.WORD,
            font=("Microsoft YaHei UI", 10),
            bg="#ffffff",
            fg="#1f2937",
            relief=tk.SOLID,
            bd=1,
            padx=8,
            pady=8
        )
        self.text_box.pack(fill=tk.BOTH, expand=True, pady=8)

        btn_frame = ttk.Frame(edit_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="应用到当前段", command=self._apply_current, style="Primary.TButton").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="保存修正版SRT", command=self._save_srt).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="试听/生成本段MP3", command=self._generate_segment_audio).pack(side=tk.LEFT, padx=6)
        ttk.Label(edit_frame, textvariable=self.modified_var).pack(anchor=tk.W, pady=(8, 0))

        action_frame = ttk.LabelFrame(root, text="输出", padding=(12, 10), style="Card.TLabelframe")
        action_frame.pack(fill=tk.X)
        ttk.Button(action_frame, text="只修字幕并重新烧录", command=self._burn_video).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(action_frame, text="批量替换已修改段声音+重新烧录", command=self._replace_audio_and_burn, style="Primary.TButton").pack(side=tk.LEFT)
        ttk.Label(action_frame, text="提示：请选择无硬字幕源视频；已烧录硬字幕的视频不能干净擦除原字幕。",
                  style="Muted.TLabel").pack(side=tk.LEFT, padx=12)

    def _choose_srt(self):
        path = filedialog.askopenfilename(title="选择SRT字幕", filetypes=[("SRT字幕", "*.srt"), ("所有文件", "*.*")])
        if path:
            self.srt_var.set(path)

    def _choose_video(self):
        path = filedialog.askopenfilename(
            title="选择 -new.mp4 源视频",
            filetypes=[("视频文件", "*.mp4;*.mov;*.mkv;*.avi"), ("所有文件", "*.*")]
        )
        if path:
            self.video_var.set(path)
            self._warn_if_hard_subbed_video(path)

    def _load_srt(self):
        path = self.srt_var.get().strip()
        if not path:
            messagebox.showwarning("提示", "请先选择SRT字幕文件")
            return
        try:
            self.srt_path = Path(path)
            self.items = self.parser.parse_file(str(self.srt_path))
            self.original_texts = {item.index: item.text for item in self.items}
            self.modified_indices = set()
            self.current_index = None
            self.saved_srt_path = None
            self.search_results = []
            self.search_pos = -1
            self.last_search_keyword = ""
            self.last_search_mode = ""
            self.search_status_var.set("")
            self._refresh_tree()
            self._update_modified_status()
            self._log(f"局部修正: 加载 {len(self.items)} 段字幕")
        except Exception as e:
            messagebox.showerror("错误", f"加载SRT失败: {str(e)}")

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for item in self.items:
            time_text = f"{item.format_time(item.start_time)} --> {item.format_time(item.end_time)}"
            preview = item.text.replace("\n", " ")
            status = "已修改" if item.index in self.modified_indices else ""
            self.tree.insert("", tk.END, iid=str(item.index), values=(item.index, status, time_text, preview))

    def _on_select(self, _event=None):
        if self.current_index is not None:
            self._apply_item(self.current_index, silent=True)
        item = self._selected_item()
        if not item:
            return
        self.current_index = item.index
        self.segment_var.set(
            f"段 {item.index}  {item.format_time(item.start_time)} --> {item.format_time(item.end_time)}"
        )
        self.text_box.delete("1.0", tk.END)
        self.text_box.insert("1.0", item.text)

    def _selected_item(self):
        selected = self.tree.selection()
        if not selected:
            return None
        index = int(selected[0])
        for item in self.items:
            if item.index == index:
                return item
        return None

    def _search(self, mode=None):
        mode = mode or self.last_search_mode or "content"
        keyword = self._get_search_keyword(mode)
        if not keyword:
            self.search_results = []
            self.search_pos = -1
            self.last_search_keyword = ""
            self.last_search_mode = ""
            self.search_status_var.set("")
            return

        results = []
        for item in self.items:
            time_text = f"{item.format_time(item.start_time)} --> {item.format_time(item.end_time)}"
            if mode == "segment":
                haystack = str(item.index).lower()
            elif mode == "time":
                haystack = time_text.lower()
            else:
                haystack = item.text.lower()
            if keyword in haystack:
                results.append(item.index)

        self.search_results = results
        self.last_search_keyword = keyword
        self.last_search_mode = mode
        self.search_pos = 0 if results else -1
        if not results:
            self.search_status_var.set("0/0")
            messagebox.showinfo("搜索", "没有找到匹配的段落")
            return
        self._select_item_by_index(results[self.search_pos])
        self._update_search_status()

    def _search_next(self):
        if self._get_search_keyword(self.last_search_mode) != self.last_search_keyword:
            self._search(self.last_search_mode)
            return
        if not self.search_results:
            self._search(self.last_search_mode)
            return
        self.search_pos = (self.search_pos + 1) % len(self.search_results)
        self._select_item_by_index(self.search_results[self.search_pos])
        self._update_search_status()

    def _search_prev(self):
        if self._get_search_keyword(self.last_search_mode) != self.last_search_keyword:
            self._search(self.last_search_mode)
            return
        if not self.search_results:
            self._search(self.last_search_mode)
            return
        self.search_pos = (self.search_pos - 1) % len(self.search_results)
        self._select_item_by_index(self.search_results[self.search_pos])
        self._update_search_status()

    def _select_item_by_index(self, index):
        iid = str(index)
        if not self.tree.exists(iid):
            return
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def _update_search_status(self):
        if not self.search_results:
            self.search_status_var.set("0/0")
            return
        self.search_status_var.set(f"{self.search_pos + 1}/{len(self.search_results)}")

    def _on_search_changed(self, _event=None):
        keyword = self._get_search_keyword(self.last_search_mode)
        if keyword != self.last_search_keyword:
            self.search_results = []
            self.search_pos = -1
            self.search_status_var.set("")

    def _get_search_keyword(self, mode):
        if mode == "segment":
            return self.segment_search_var.get().strip().lower()
        if mode == "time":
            return self.time_search_var.get().strip().lower()
        if mode == "content":
            return self.content_search_var.get().strip().lower()
        return ""

    def _apply_current(self):
        item = self._selected_item()
        if not item:
            messagebox.showwarning("提示", "请先选择一个字幕段")
            return False
        self._apply_item(item.index, silent=False)
        return True

    def _apply_item(self, index, silent=False):
        item = self._find_item(index)
        if not item:
            return False
        new_text = self.text_box.get("1.0", tk.END).strip()
        item.text = new_text
        original = self.original_texts.get(item.index, "")
        if new_text != original:
            self.modified_indices.add(item.index)
        else:
            self.modified_indices.discard(item.index)
        self.tree.set(str(item.index), "status", "已修改" if item.index in self.modified_indices else "")
        self.tree.set(str(item.index), "text", item.text.replace("\n", " "))
        self._update_modified_status()
        if not silent:
            self._log(f"局部修正: 已应用第 {item.index} 段，当前共修改 {len(self.modified_indices)} 段")
        return True

    def _find_item(self, index):
        for item in self.items:
            if item.index == index:
                return item
        return None

    def _update_modified_status(self):
        self.modified_var.set(f"已修改 {len(self.modified_indices)} 段")

    def _save_srt(self, show_message=True):
        if not self.items or not self.srt_path:
            messagebox.showwarning("提示", "请先加载SRT字幕")
            return None
        if self.current_index is not None:
            self._apply_item(self.current_index, silent=True)
        output_path = self.srt_path.parent / f"{self.srt_path.stem}_局部修正版.srt"
        try:
            self.parser.write_file(self.items, str(output_path))
            self.saved_srt_path = output_path
            self._log(f"局部修正: 已保存 {output_path}")
            if show_message:
                messagebox.showinfo("完成", f"已保存修正版SRT:\n{output_path}")
            return output_path
        except Exception as e:
            messagebox.showerror("错误", f"保存SRT失败: {str(e)}")
            return None

    def _generate_segment_audio(self):
        item = self._selected_item()
        if not item:
            messagebox.showwarning("提示", "请先选择一个字幕段")
            return
        self._apply_current()
        if not self.srt_path:
            messagebox.showwarning("提示", "请先加载SRT字幕")
            return
        output_path = self.srt_path.parent / f"{self.srt_path.stem}_seg_{item.index:04d}.mp3"
        text = item.text.strip()
        if not text:
            messagebox.showwarning("提示", "当前段字幕为空，无法生成配音")
            return

        def run():
            try:
                self._log(f"局部修正: 正在生成第 {item.index} 段配音...")
                asyncio.run(self.tts_engine.synthesize_segment(text, self.voice_getter(), str(output_path)))
                self._log(f"局部修正: 单段配音已生成 {output_path}")
                self.window.after(0, lambda: messagebox.showinfo("完成", f"已生成本段配音:\n{output_path}"))
            except Exception as e:
                self._log(f"局部修正: 生成本段配音失败: {str(e)}")
                error = str(e)
                self.window.after(0, lambda: messagebox.showerror("错误", f"生成本段配音失败: {error}"))

        threading.Thread(target=run, daemon=True).start()

    def _warn_if_hard_subbed_video(self, video_path):
        stem = Path(video_path).stem.lower()
        hard_sub_markers = ("_final", "-final", "_sub", "-sub", "硬字幕")
        if any(marker in stem for marker in hard_sub_markers):
            messagebox.showwarning(
                "请确认源视频",
                "你选择的视频文件名看起来像已经烧录过硬字幕的成品。\n\n"
                "局部修正应选择无硬字幕源视频，例如合并音视频后的 -new.mp4。\n"
                "如果直接使用已烧录硬字幕的视频，新的字幕会和旧字幕重叠。"
            )

    def _validate_video_path(self):
        video_path = self.video_var.get().strip()
        if not video_path:
            messagebox.showwarning("提示", "请先选择合并音视频生成的 -new.mp4 源视频")
            return None
        path = Path(video_path)
        if not path.exists():
            messagebox.showwarning("提示", "视频文件不存在")
            return None
        stem = path.stem.lower()
        if stem.endswith("-mute") or stem.endswith("_mute"):
            messagebox.showwarning(
                "源视频选择错误",
                "当前选择的是去声音后的 mute 视频，它没有原音轨。\n\n"
                "局部修正声音时应选择“合并音视频”生成的 -new.mp4，"
                "这样程序才能保留其他位置的声音，只替换修订段。"
            )
            return None
        hard_sub_markers = ("_final", "-final", "_sub", "-sub", "硬字幕")
        if any(marker in stem for marker in hard_sub_markers):
            ok = messagebox.askyesno(
                "可能会字幕重叠",
                "当前视频看起来像已经烧录硬字幕的成品。\n\n"
                "硬字幕已经变成画面像素，无法可靠清除；继续处理会导致新旧字幕重叠。\n"
                "建议取消，改选无硬字幕源视频（例如 -new.mp4）。\n\n"
                "仍然继续吗？"
            )
            if not ok:
                return None
        return path

    def _burn_srt_to_video(self, video_path, srt_path, output_path):
        ffmpeg = FFmpegExecutor(config_manager.get_ffmpeg_path())

        def log_line(line):
            self._log(f"    {line}")

        ffmpeg.burn_subtitle(
            str(video_path),
            str(srt_path),
            str(output_path),
            use_hardware_accel=self.hardware_accel_getter(),
            callback=log_line
        )

    def _burn_video(self):
        srt_path = self._save_srt()
        if not srt_path:
            return
        video_path = self._validate_video_path()
        if not video_path:
            return
        output_path = video_path.parent / f"{video_path.stem}_局部修正版.mp4"

        def run():
            try:
                self._log("局部修正: 开始用修正版SRT重新烧录视频...")
                if self.progress_callback:
                    self.progress_callback(15, 100, "准备重新烧录...")
                self._burn_srt_to_video(video_path, srt_path, output_path)
                if self.progress_callback:
                    self.progress_callback(100, 100, "局部修正完成")
                self._log(f"局部修正: 已输出 {output_path}")
                self.window.after(0, lambda: messagebox.showinfo("完成", f"已生成修正版视频:\n{output_path}"))
            except Exception as e:
                self._log(f"局部修正: 重新烧录失败: {str(e)}")
                error = str(e)
                self.window.after(0, lambda: messagebox.showerror("错误", f"重新烧录失败: {error}"))

        threading.Thread(target=run, daemon=True).start()

    def _replace_audio_and_burn(self):
        if self.current_index is not None:
            self._apply_item(self.current_index, silent=True)
        changed_items = [item for item in self.items if item.index in self.modified_indices]
        if not changed_items:
            messagebox.showwarning("提示", "请先修改一个或多个字幕段")
            return
        invalid_items = [item.index for item in changed_items if item.end_time <= item.start_time]
        if invalid_items:
            messagebox.showwarning("提示", f"以下段落时间戳无效，无法替换声音: {invalid_items}")
            return
        empty_items = [item.index for item in changed_items if not item.text.strip()]
        if empty_items:
            messagebox.showwarning("提示", f"以下段落字幕为空，无法生成替换配音: {empty_items}")
            return

        srt_path = self._save_srt(show_message=False)
        if not srt_path:
            return
        video_path = self._validate_video_path()
        if not video_path:
            return

        output_path = video_path.parent / f"{video_path.stem}_局部修正版.mp4"

        def run():
            try:
                total = len(changed_items)
                self._log(f"局部修正: 开始批量替换 {total} 段声音...")
                if self.progress_callback:
                    self.progress_callback(5, 100, f"准备替换 {total} 段声音...")

                with tempfile.TemporaryDirectory(prefix="video_tool_localfix_") as temp_dir:
                    temp_dir_path = Path(temp_dir)
                    segment_infos = []
                    audio_fixed_video = temp_dir_path / f"{video_path.stem}_audio_fixed.mp4"

                    for pos, item in enumerate(changed_items, start=1):
                        base_progress = 5 + int((pos - 1) / total * 45)
                        if self.progress_callback:
                            self.progress_callback(base_progress, 100, f"生成第 {item.index} 段配音 ({pos}/{total})...")

                        raw_audio = temp_dir_path / f"seg_{item.index:04d}_raw.mp3"
                        aligned_audio = temp_dir_path / f"seg_{item.index:04d}_aligned.m4a"
                        self._log(f"局部修正: 生成第 {item.index} 段配音 ({pos}/{total})")
                        asyncio.run(
                            self.tts_engine.synthesize_segment(
                                item.text.strip(),
                                self.voice_getter(),
                                str(raw_audio)
                            )
                        )

                        if self.progress_callback:
                            self.progress_callback(base_progress + 3, 100, f"对齐第 {item.index} 段配音时长...")
                        self._align_audio_to_segment(raw_audio, aligned_audio, item.end_time - item.start_time)
                        segment_infos.append({
                            "index": item.index,
                            "audio": aligned_audio,
                            "start": item.start_time,
                            "end": item.end_time,
                        })

                    if self.progress_callback:
                        self.progress_callback(55, 100, "批量替换原视频对应时间段声音...")
                    self._replace_video_audio_segments(
                        video_path,
                        segment_infos,
                        audio_fixed_video,
                    )

                    if self.progress_callback:
                        self.progress_callback(75, 100, "重新烧录修正版字幕...")
                    self._burn_srt_to_video(audio_fixed_video, srt_path, output_path)

                if self.progress_callback:
                    self.progress_callback(100, 100, "局部修正完成")
                self._log(f"局部修正: 已输出 {output_path}")
                self.window.after(0, lambda: messagebox.showinfo("完成", f"已生成修正版视频:\n{output_path}"))
            except Exception as e:
                self._log(f"局部修正: 批量替换声音失败: {str(e)}")
                error = str(e)
                self.window.after(0, lambda: messagebox.showerror("错误", f"批量替换声音失败: {error}"))

        threading.Thread(target=run, daemon=True).start()

    def _align_audio_to_segment(self, input_audio, output_audio, duration):
        ffmpeg = FFmpegExecutor(config_manager.get_ffmpeg_path())
        duration = max(0.05, float(duration))
        args = [
            "-i", str(input_audio),
            "-af", f"apad,atrim=0:{duration:.3f}",
            "-ac", "2",
            "-ar", "48000",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y",
            str(output_audio)
        ]
        ffmpeg.run_command(args, callback=lambda line: self._log(f"    {line}"))

    def _replace_video_audio_segment(self, video_path, segment_audio, output_path, start_time, end_time):
        self._replace_video_audio_segments(
            video_path,
            [{"audio": segment_audio, "start": start_time, "end": end_time}],
            output_path
        )

    def _replace_video_audio_segments(self, video_path, segment_infos, output_path):
        ffmpeg = FFmpegExecutor(config_manager.get_ffmpeg_path())
        args = ["-i", str(video_path)]
        for info in segment_infos:
            args.extend(["-i", str(info["audio"])])

        volume_filters = []
        overlay_filters = []
        mix_inputs = ["[a0]"]
        for pos, info in enumerate(segment_infos, start=1):
            start = float(info["start"])
            end = float(info["end"])
            delay_ms = max(0, int(round(start * 1000)))
            volume_filters.append(f"volume=enable='between(t\\,{start:.3f}\\,{end:.3f})':volume=0")
            overlay_filters.append(f"[{pos}:a]adelay={delay_ms}|{delay_ms},apad[a{pos}]")
            mix_inputs.append(f"[a{pos}]")

        original_audio_filter = f"[0:a]{','.join(volume_filters)}[a0]"
        filter_complex = ";".join(
            [original_audio_filter]
            + overlay_filters
            + [f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0[aout]"]
        )
        args = [
            *args,
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y",
            str(output_path)
        ]
        ffmpeg.run_command(args, callback=lambda line: self._log(f"    {line}"))

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
