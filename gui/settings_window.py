"""
大模型设置窗口
"""
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

class ModelSettingsWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("大模型设置")
        self.window.geometry("700x500")
        self.window.transient(parent)
        self.window.grab_set()

        # 配置文件路径
        self.config_file = os.path.join(os.path.dirname(__file__), "..", "..", "model_settings.json")
        self.config_file = os.path.abspath(self.config_file)

        # 加载配置
        self.settings = self.load_settings()

        self.create_widgets()

    def load_settings(self):
        """加载设置"""
        default_settings = {
            "api_key": "",
            "api_url": "https://api.minimaxi.com/v1",
            "models": {
                "MiniMax-abab6.5s-chat": "abab6.5s-chat",
                "MiniMax-abab6-chat": "abab6-chat",
                "MiniMax-chat": "chat"
            },
            "current_model": "MiniMax-abab6.5s-chat"
        }

        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # 合并配置
                    for key in default_settings:
                        if key not in loaded:
                            loaded[key] = default_settings[key]
                    return loaded
        except:
            pass

        return default_settings

    def save_settings(self):
        """保存设置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            messagebox.showerror("错误", f"保存设置失败: {str(e)}")
            return False

    def create_widgets(self):
        # API设置区域
        api_frame = ttk.LabelFrame(self.window, text="API设置", padding=10)
        api_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(api_frame, text="API密钥:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.api_key_var = tk.StringVar(value=self.settings.get("api_key", ""))
        ttk.Entry(api_frame, textvariable=self.api_key_var, width=60).grid(row=0, column=1, padx=5)

        ttk.Label(api_frame, text="API地址:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.api_url_var = tk.StringVar(value=self.settings.get("api_url", ""))
        ttk.Entry(api_frame, textvariable=self.api_url_var, width=60).grid(row=1, column=1, padx=5)

        # 模型列表区域
        list_frame = ttk.LabelFrame(self.window, text="模型列表", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 模型列表框
        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.model_listbox = tk.Listbox(listbox_frame, height=10, yscrollcommand=scrollbar.set)
        self.model_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.model_listbox.yview)

        # 填充模型列表
        self.models = self.settings.get("models", {})
        for name in self.models.keys():
            self.model_listbox.insert(tk.END, name)

        self.model_listbox.bind('<<ListboxSelect>>', self.on_model_select)

        # 模型编辑区域
        edit_frame = ttk.Frame(list_frame)
        edit_frame.pack(fill=tk.X, pady=5)

        # 第一行：显示名称
        name_row = ttk.Frame(edit_frame)
        name_row.pack(fill=tk.X, pady=2)
        ttk.Label(name_row, text="显示名称:").pack(side=tk.LEFT, padx=5)
        self.display_name_var = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.display_name_var, width=25).pack(side=tk.LEFT, padx=5)

        # 第二行：模型ID
        id_row = ttk.Frame(edit_frame)
        id_row.pack(fill=tk.X, pady=2)
        ttk.Label(id_row, text="模型ID:").pack(side=tk.LEFT, padx=5)
        self.model_id_var = tk.StringVar()
        ttk.Entry(id_row, textvariable=self.model_id_var, width=25).pack(side=tk.LEFT, padx=5)

        # 按钮区域
        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="添加", command=self.add_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="更新", command=self.update_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="删除", command=self.delete_model).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="设为默认", command=self.set_default).pack(side=tk.LEFT, padx=5)

        # 当前默认模型
        default_frame = ttk.Frame(self.window)
        default_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(default_frame, text="当前使用:").pack(side=tk.LEFT, padx=5)
        self.current_var = tk.StringVar(value=self.settings.get("current_model", ""))
        current_models = list(self.models.keys()) if self.models else ["无"]
        self.current_combo = ttk.Combobox(default_frame, textvariable=self.current_var,
                                          values=current_models, state="readonly", width=25)
        self.current_combo.pack(side=tk.LEFT, padx=5)

        # 底部按钮
        bottom_frame = ttk.Frame(self.window)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(bottom_frame, text="保存并应用", command=self.apply_and_save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bottom_frame, text="取消", command=self.window.destroy).pack(side=tk.RIGHT, padx=5)

    def on_model_select(self, event):
        """选中模型时填充编辑框"""
        selection = self.model_listbox.curselection()
        if not selection:
            return

        name = self.model_listbox.get(selection[0])
        model_id = self.models.get(name, "")

        self.display_name_var.set(name)
        self.model_id_var.set(model_id)

    def add_model(self):
        """添加模型"""
        display_name = self.display_name_var.get().strip()
        model_id = self.model_id_var.get().strip()

        if not display_name or not model_id:
            messagebox.showwarning("警告", "请输入显示名称和模型ID")
            return

        if display_name in self.models:
            messagebox.showwarning("警告", "该名称已存在")
            return

        self.models[display_name] = model_id
        self.model_listbox.insert(tk.END, display_name)
        self.current_combo['values'] = list(self.models.keys())

        # 清空输入
        self.display_name_var.set("")
        self.model_id_var.set("")

    def update_model(self):
        """更新模型"""
        selection = self.model_listbox.curselection()
        if not selection:
            messagebox.showwarning("警告", "请先选择要更新的模型")
            return

        old_name = self.model_listbox.get(selection[0])
        new_display = self.display_name_var.get().strip()
        new_id = self.model_id_var.get().strip()

        if not new_display or not new_id:
            messagebox.showwarning("警告", "请输入显示名称和模型ID")
            return

        # 更新
        if old_name != new_display:
            del self.models[old_name]
            self.models[new_display] = new_id
            self.model_listbox.delete(selection[0])
            self.model_listbox.insert(selection[0], new_display)
        else:
            self.models[old_name] = new_id

        self.current_combo['values'] = list(self.models.keys())

    def delete_model(self):
        """删除模型"""
        selection = self.model_listbox.curselection()
        if not selection:
            return

        name = self.model_listbox.get(selection[0])
        if messagebox.askyesno("确认", f"确定删除模型 '{name}' 吗？"):
            del self.models[name]
            self.model_listbox.delete(selection[0])
            self.current_combo['values'] = list(self.models.keys())
            self.display_name_var.set("")
            self.model_id_var.set("")

    def set_default(self):
        """设为默认"""
        selection = self.model_listbox.curselection()
        if not selection:
            return

        name = self.model_listbox.get(selection[0])
        self.current_var.set(name)

    def apply_and_save(self):
        """保存并应用"""
        # 更新API设置
        self.settings["api_key"] = self.api_key_var.get().strip()
        self.settings["api_url"] = self.api_url_var.get().strip()
        self.settings["models"] = self.models
        self.settings["current_model"] = self.current_var.get()

        # 保存到文件
        if self.save_settings():
            # 更新全局配置
            from ..core.translator_engine import update_translation_config
            update_translation_config(
                api_key=self.settings["api_key"],
                api_url=self.settings["api_url"],
                models=self.settings["models"],
                current_model=self.settings["current_model"]
            )

            messagebox.showinfo("成功", "设置已保存并应用")
            self.window.destroy()
