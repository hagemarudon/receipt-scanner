"""Windows 向けの画面 (tkinter)。"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from . import APP_NAME
from .loader import SUPPORTED_EXTENSIONS, is_supported
from .ocr import LANGUAGES, OcrEngine, OcrError
from .processor import Cancelled, FileResult, process_file
from .settings import Settings, load_settings, save_settings

try:  # ドラッグ＆ドロップ (入っていなければ「ファイルを追加」だけで使う)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    TkinterDnD = None

FORMAT_LABELS = {"txt": "テキスト (.txt)", "csv": "表 (.csv)", "pdf": "PDF (.pdf)"}
PDF_MODE_LABELS = {"searchable": "元の画像＋文字 (検索・コピーできる)", "text": "文字だけ"}
ENCODING_LABELS = {"utf-8-sig": "UTF-8", "cp932": "Shift_JIS"}

STATUS_WAITING = "待機中"
STATUS_DONE = "完了"


def _label_for(mapping: dict[str, str], value: str) -> str:
    return mapping.get(value, next(iter(mapping.values())))


def _value_for(mapping: dict[str, str], label: str) -> str:
    return next((k for k, v in mapping.items() if v == label), next(iter(mapping)))


def open_path(path: Path, select: bool = False) -> None:
    if sys.platform == "win32":
        if select:
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(path)  # noqa: S606 - 利用者が作ったファイルを既定のアプリで開く
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.parent if select else path)])


class App:
    def __init__(self, root: tk.Tk, settings_path: Path | None = None):
        self.root = root
        self.settings_path = settings_path
        self.settings = load_settings(settings_path)
        self.files: dict[str, Path] = {}
        self.results: dict[str, FileResult] = {}
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.dnd = TkinterDnD is not None and getattr(root, "TkdndVersion", None) is not None

        root.title(APP_NAME)
        root.geometry("900x740")
        root.minsize(720, 600)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name).configure(size=11)
        style = ttk.Style(root)
        style.configure("Treeview", rowheight=26)
        family = font.nametofont("TkDefaultFont").actual("family")
        style.configure("Accent.TButton", font=(family, 12, "bold"), padding=(16, 6))

        self._build()
        self._load_settings_into_widgets()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll_events)

    # ---------- 画面の組み立て ----------

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        main.rowconfigure(5, weight=2)

        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.add_files_button = ttk.Button(bar, text="ファイルを追加…", command=self.add_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(bar, text="フォルダを追加…", command=self.add_folder)
        self.add_folder_button.pack(side="left", padx=6)
        self.remove_button = ttk.Button(bar, text="リストから外す", command=self.remove_selected)
        self.remove_button.pack(side="left")

        list_frame = ttk.Frame(main)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_frame, columns=("status", "folder"), height=5, selectmode="extended")
        self.tree.heading("#0", text="ファイル", anchor="w")
        self.tree.heading("status", text="状態", anchor="w")
        self.tree.heading("folder", text="場所", anchor="w")
        self.tree.column("#0", width=260, stretch=False)
        self.tree.column("status", width=200, stretch=False)
        self.tree.column("folder", width=300, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_result())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected_output())
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())

        hint = "ここにファイルをドラッグ＆ドロップ" if self.dnd else "「ファイルを追加…」から選んでください"
        background = ttk.Style(self.root).lookup("Treeview", "fieldbackground") or "white"
        self.empty_label = tk.Label(
            list_frame,
            text=f"JPG・PDF をまだ追加していません\n{hint}",
            justify="center",
            foreground="gray",
            background=background,
        )
        if self.dnd:
            for widget in (self.tree, self.empty_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        self._build_output_settings(main).grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._build_menu()

        run = ttk.Frame(main)
        run.grid(row=4, column=0, sticky="ew", pady=10)
        run.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(run, text="文字起こしを開始", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(run, text="中止", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=6)
        self.progress = ttk.Progressbar(run, mode="determinate")
        self.progress.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.status = tk.StringVar()
        ttk.Label(run, textvariable=self.status).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        result = ttk.LabelFrame(main, text="文字起こし結果", padding=8)
        result.grid(row=5, column=0, sticky="nsew")
        result.columnconfigure(0, weight=1)
        result.rowconfigure(1, weight=1)
        actions = ttk.Frame(result)
        actions.grid(row=0, column=0, columnspan=2, sticky="e", pady=(0, 4))
        self.copy_button = ttk.Button(actions, text="コピー", command=self.copy_text, state="disabled")
        self.copy_button.pack(side="left")
        self.open_button = ttk.Button(
            actions, text="保存したファイルを開く", command=self.open_selected_output, state="disabled"
        )
        self.open_button.pack(side="left", padx=6)
        self.folder_button = ttk.Button(
            actions, text="保存先フォルダを開く", command=self.open_selected_folder, state="disabled"
        )
        self.folder_button.pack(side="left")
        self.output_label = ttk.Label(result, foreground="gray")
        self.output_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.text = tk.Text(
            result, wrap="char", height=10, font=("Yu Gothic UI", 11) if sys.platform == "win32" else None
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(result, orient="vertical", command=self.text.yview)
        text_scroll.grid(row=1, column=1, sticky="ns")
        self.text.configure(yscrollcommand=text_scroll.set, state="disabled")

        self._refresh_empty_state()

    def _build_output_settings(self, parent) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="出力", padding=8)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="形式").grid(row=0, column=0, sticky="w", padx=(0, 12))
        formats = ttk.Frame(frame)
        formats.grid(row=0, column=1, columnspan=2, sticky="w")
        self.format_var = tk.StringVar()
        for value, label in FORMAT_LABELS.items():
            ttk.Radiobutton(
                formats, text=label, value=value, variable=self.format_var, command=self._sync_widgets
            ).pack(side="left", padx=(0, 16))

        ttk.Label(frame, text="PDF の中身").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.pdf_mode_var = tk.StringVar()
        self.pdf_mode_box = ttk.Combobox(
            frame, textvariable=self.pdf_mode_var, values=list(PDF_MODE_LABELS.values()), state="readonly", width=34
        )
        self.pdf_mode_box.grid(row=1, column=1, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="文字コード").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.encoding_var = tk.StringVar()
        self.encoding_box = ttk.Combobox(
            frame, textvariable=self.encoding_var, values=list(ENCODING_LABELS.values()), state="readonly", width=14
        )
        self.encoding_box.grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="保存先").grid(row=3, column=0, sticky="w", pady=(6, 0))
        dest = ttk.Frame(frame)
        dest.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        dest.columnconfigure(2, weight=1)
        self.dest_mode = tk.StringVar()
        ttk.Radiobutton(
            dest, text="元のファイルと同じフォルダ", value="same", variable=self.dest_mode, command=self._sync_widgets
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            dest, text="指定したフォルダ", value="custom", variable=self.dest_mode, command=self._sync_widgets
        ).grid(row=0, column=1, sticky="w", padx=(16, 6))
        self.output_dir_var = tk.StringVar()
        self.output_dir_entry = ttk.Entry(dest, textvariable=self.output_dir_var)
        self.output_dir_entry.grid(row=0, column=2, sticky="ew")
        self.output_dir_button = ttk.Button(dest, text="参照…", command=self.choose_output_dir)
        self.output_dir_button.grid(row=0, column=3, padx=(6, 0))

        ttk.Label(frame, text="書類の言語").grid(row=4, column=0, sticky="w", pady=(6, 0))
        reading = ttk.Frame(frame)
        reading.grid(row=4, column=1, columnspan=2, sticky="w", pady=(6, 0))
        self.language_var = tk.StringVar()
        ttk.Combobox(reading, textvariable=self.language_var, values=list(LANGUAGES), state="readonly", width=16).pack(
            side="left"
        )
        self.rotate_var = tk.BooleanVar()
        ttk.Checkbutton(reading, text="横向き・逆さまのスキャンを自動で直す", variable=self.rotate_var).pack(
            side="left", padx=(16, 0)
        )
        self.tesseract_var = tk.StringVar()
        return frame

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="Tesseract の場所を指定…", command=self.choose_tesseract)
        settings_menu.add_command(label="Tesseract の場所を自動で探す", command=lambda: self.tesseract_var.set(""))
        menubar.add_cascade(label="設定", menu=settings_menu)
        self.root.configure(menu=menubar)

    # ---------- 設定 ----------

    def _load_settings_into_widgets(self) -> None:
        s = self.settings
        self.format_var.set(s.output_format)
        self.pdf_mode_var.set(_label_for(PDF_MODE_LABELS, s.pdf_mode))
        self.encoding_var.set(_label_for(ENCODING_LABELS, s.encoding))
        self.dest_mode.set("custom" if s.output_dir else "same")
        self.output_dir_var.set(s.output_dir)
        self.language_var.set(next((k for k, v in LANGUAGES.items() if v == s.language), next(iter(LANGUAGES))))
        self.rotate_var.set(s.auto_rotate)
        self.tesseract_var.set(s.tesseract_path)
        self._sync_widgets()

    def _settings_from_widgets(self) -> Settings:
        return Settings(
            output_format=self.format_var.get(),
            pdf_mode=_value_for(PDF_MODE_LABELS, self.pdf_mode_var.get()),
            encoding=_value_for(ENCODING_LABELS, self.encoding_var.get()),
            output_dir=self.output_dir_var.get().strip() if self.dest_mode.get() == "custom" else "",
            language=LANGUAGES.get(self.language_var.get(), "jpn"),
            auto_rotate=self.rotate_var.get(),
            tesseract_path=self.tesseract_var.get().strip(),
        ).validated()

    def _save_settings(self) -> None:
        self.settings = self._settings_from_widgets()
        try:
            save_settings(self.settings, self.settings_path)
        except OSError:
            pass  # 保存できなくても文字起こしはできるので止めない

    def _sync_widgets(self) -> None:
        fmt = self.format_var.get()
        self.pdf_mode_box.configure(state="readonly" if fmt == "pdf" else "disabled")
        self.encoding_box.configure(state="disabled" if fmt == "pdf" else "readonly")
        custom = "normal" if self.dest_mode.get() == "custom" else "disabled"
        self.output_dir_entry.configure(state=custom)
        self.output_dir_button.configure(state=custom)

    def choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(title="保存先フォルダ")
        if folder:
            self.output_dir_var.set(folder)

    def choose_tesseract(self) -> None:
        path = filedialog.askopenfilename(
            title="tesseract.exe の場所", filetypes=[("tesseract", "tesseract*"), ("すべて", "*")]
        )
        if path:
            self.tesseract_var.set(path)

    # ---------- ファイル一覧 ----------

    def add_paths(self, paths) -> int:
        known = set(self.files.values())
        added = 0
        for raw in paths:
            path = Path(raw)
            candidates = sorted(p for p in path.iterdir() if p.is_file()) if path.is_dir() else [path]
            for candidate in candidates:
                if not is_supported(candidate) or candidate in known:
                    continue
                item = self.tree.insert("", "end", text=candidate.name, values=(STATUS_WAITING, str(candidate.parent)))
                self.files[item] = candidate
                known.add(candidate)
                added += 1
        self._refresh_empty_state()
        return added

    def add_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="スキャンした書類", filetypes=[("画像・PDF", patterns), ("すべて", "*")]
        )
        self.add_paths(paths)

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="スキャンした書類のフォルダ")
        if folder and self.add_paths([folder]) == 0:
            messagebox.showinfo(APP_NAME, "このフォルダには JPG・PDF などの対応ファイルがありません。")

    def _on_drop(self, event) -> None:
        self.add_paths(self.root.tk.splitlist(event.data))

    def remove_selected(self) -> None:
        if self._running:
            return
        for item in self.tree.selection():
            self.tree.delete(item)
            self.files.pop(item, None)
            self.results.pop(item, None)
        self._refresh_empty_state()
        self._show_selected_result()

    def _refresh_empty_state(self) -> None:
        if self.files:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.55, anchor="center")

    # ---------- 実行 ----------

    @property
    def _running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(self) -> None:
        if self._running:
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "文字起こしするファイルを追加してください。")
            return
        targets = [(item, path) for item, path in self.files.items() if self.tree.set(item, "status") != STATUS_DONE]
        if not targets:
            # 形式を変えてもう一度保存したいときなど
            if not messagebox.askyesno(APP_NAME, "すべて完了しています。もう一度文字起こししますか？"):
                return
            targets = list(self.files.items())
        if self.dest_mode.get() == "custom" and not self.output_dir_var.get().strip():
            messagebox.showwarning(APP_NAME, "保存先フォルダを指定してください。")
            return
        self._save_settings()

        self.cancel.clear()
        self.progress.configure(maximum=len(targets), value=0)
        self._set_running(True)
        self.worker = threading.Thread(target=self._work, args=(targets, self.settings), daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.cancel.set()
        self.status.set("中止しています…")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for button in (self.start_button, self.add_files_button, self.add_folder_button, self.remove_button):
            button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _work(self, targets: list[tuple[str, Path]], settings: Settings) -> None:
        """別スレッドで動く。画面の操作は events 経由でメインスレッドに任せる。"""
        post = self.events.put
        try:
            engine = OcrEngine(settings.tesseract_path, settings.language, settings.auto_rotate)
        except OcrError as e:
            post(("fatal", str(e)))
            return
        for index, (item, path) in enumerate(targets):
            if self.cancel.is_set():
                break
            post(("status", item, "処理中…", index, path.name))
            try:
                result = process_file(
                    path,
                    settings,
                    engine,
                    on_page=lambda n, total, item=item: post(
                        ("status", item, f"処理中… {n}/{total}ページ", None, None)
                    ),
                    cancel=self.cancel,
                )
            except Cancelled:
                post(("status", item, STATUS_WAITING, None, None))
                break
            except Exception as e:  # 1 ファイルの失敗で全体を止めない
                post(("error", item, str(e) or type(e).__name__))
            else:
                post(("done", item, result))
            post(("progress", index + 1))
        post(("finished",))

    def _poll_events(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "status":
            _, item, text, _index, name = event
            if self.tree.exists(item):
                self.tree.set(item, "status", text)
            if name:
                self.status.set(f"{name} を読み取っています")
        elif kind == "done":
            _, item, result = event
            self.results[item] = result
            if self.tree.exists(item):
                self.tree.set(item, "status", STATUS_DONE)
                self.tree.selection_set(item)
                self.tree.see(item)
        elif kind == "error":
            _, item, message = event
            if self.tree.exists(item):
                self.tree.set(item, "status", f"エラー: {message.splitlines()[0]}")
        elif kind == "progress":
            self.progress.configure(value=event[1])
        elif kind == "fatal":
            self._set_running(False)
            self.status.set("")
            messagebox.showerror(APP_NAME, event[1])
        elif kind == "finished":
            self._set_running(False)
            done = sum(1 for item in self.files if self.tree.set(item, "status") == STATUS_DONE)
            failed = sum(1 for item in self.files if self.tree.set(item, "status").startswith("エラー"))
            message = f"{done} 件完了"
            if failed:
                message += f"、{failed} 件エラー"
            if self.cancel.is_set():
                message += " (中止しました)"
            self.status.set(message)

    # ---------- 結果 ----------

    def _selected_result(self) -> FileResult | None:
        for item in self.tree.selection():
            if item in self.results:
                return self.results[item]
        return None

    def _show_selected_result(self) -> None:
        result = self._selected_result()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if result:
            self.text.insert("1.0", result.text)
        self.text.configure(state="disabled")
        self.output_label.configure(text=f"保存先: {result.output}" if result else "")
        state = "normal" if result else "disabled"
        for button in (self.copy_button, self.open_button, self.folder_button):
            button.configure(state=state)

    def copy_text(self) -> None:
        result = self._selected_result()
        if result:
            self.root.clipboard_clear()
            self.root.clipboard_append(result.text)
            self.status.set("コピーしました")

    def open_selected_output(self) -> None:
        result = self._selected_result()
        if result and result.output.exists():
            open_path(result.output)

    def open_selected_folder(self) -> None:
        result = self._selected_result()
        if result and result.output.exists():
            open_path(result.output, select=True)

    def on_close(self) -> None:
        if self._running and not messagebox.askyesno(APP_NAME, "文字起こしの途中です。終了しますか？"):
            return
        self.cancel.set()
        self._save_settings()
        self.root.destroy()


def _enable_high_dpi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main() -> int:
    _enable_high_dpi()
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    App(root)
    root.mainloop()
    return 0
