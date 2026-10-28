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


# カルテ・処方箋の用紙から取った色
PAPER = "#F2F6F5"  # 背景 (うすい青緑の用紙)
SHEET = "#FFFFFF"  # 一覧・結果の紙面
INK = "#1F2A37"  # 文字
MUTED = "#5E6E6B"  # 補足の文字
RULE = "#C5D3D0"  # 罫線
GREEN = "#1D6B5C"  # 主な操作と選択中 (処方箋の緑)
GREEN_DARK = "#17574B"
GREEN_PALE = "#DCEDE8"
RED = "#B3261E"

# 高齢の方にも読みやすいユニバーサルデザインのフォント (Windows 10 以降に標準で入っている)
UI_FONTS = ("BIZ UDPゴシック", "BIZ UDPGothic", "Yu Gothic UI", "Meiryo UI", "Noto Sans CJK JP")
MONO_FONTS = ("BIZ UDゴシック", "BIZ UDGothic", "MS Gothic", "Noto Sans Mono CJK JP")


def _pick_font(candidates: tuple[str, ...], fallback: str) -> str:
    available = set(font.families())
    return next((name for name in candidates if name in available), fallback)


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
        root.geometry("1040x720")  # 1366x768 の画面でも収まる高さ
        root.minsize(900, 640)
        root.configure(background=PAPER)
        self._setup_style()

        self._build()
        self._load_settings_into_widgets()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll_events)

    # ---------- 見た目 ----------

    def _setup_style(self) -> None:
        family = _pick_font(UI_FONTS, font.nametofont("TkDefaultFont").actual("family"))
        self.mono_family = _pick_font(MONO_FONTS, family)
        self.ui_family = family
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            font.nametofont(name).configure(family=family, size=12)

        style = ttk.Style(self.root)
        style.theme_use("clam")  # 色を細かく指定できるテーマ
        style.configure(".", background=PAPER, foreground=INK, font=(family, 12), bordercolor=RULE)
        style.configure("TFrame", background=PAPER)
        style.configure("Sheet.TFrame", background=SHEET)
        style.configure("TLabel", background=PAPER, foreground=INK)
        style.configure("Sheet.TLabel", background=SHEET)
        style.configure("Muted.TLabel", foreground=MUTED, font=(family, 11))
        style.configure("SheetMuted.TLabel", background=SHEET, foreground=MUTED, font=(family, 11))
        style.configure("Title.TLabel", font=(family, 18, "bold"))
        style.configure("Heading.TLabel", font=(family, 13, "bold"))
        style.configure("SheetHeading.TLabel", background=SHEET, font=(family, 13, "bold"))

        style.configure(
            "TButton",
            background=SHEET,
            foreground=INK,
            padding=(14, 6),
            borderwidth=1,
            bordercolor=RULE,
            lightcolor=SHEET,
            darkcolor=SHEET,
        )
        style.map(
            "TButton",
            background=[("disabled", PAPER), ("pressed", GREEN_PALE), ("active", "#E8F1EF")],
            lightcolor=[("disabled", PAPER), ("pressed", GREEN_PALE), ("active", "#E8F1EF")],
            darkcolor=[("disabled", PAPER), ("pressed", GREEN_PALE), ("active", "#E8F1EF")],
            foreground=[("disabled", "#9AA7A4")],
            bordercolor=[("focus", GREEN)],
        )
        style.configure(
            "Primary.TButton",
            background=GREEN,
            foreground="white",
            font=(family, 15, "bold"),
            padding=(32, 12),
            bordercolor=GREEN,
            lightcolor=GREEN,
            darkcolor=GREEN,
        )
        style.map(
            "Primary.TButton",
            background=[("disabled", "#A9C3BD"), ("pressed", GREEN_DARK), ("active", GREEN_DARK)],
            lightcolor=[("disabled", "#A9C3BD"), ("pressed", GREEN_DARK), ("active", GREEN_DARK)],
            darkcolor=[("disabled", "#A9C3BD"), ("pressed", GREEN_DARK), ("active", GREEN_DARK)],
            foreground=[("disabled", "white")],
            bordercolor=[("focus", INK)],
        )

        style.configure(
            "Treeview",
            background=SHEET,
            fieldbackground=SHEET,
            foreground=INK,
            rowheight=34,
            borderwidth=0,
            font=(family, 12),
        )
        style.map("Treeview", background=[("selected", GREEN_PALE)], foreground=[("selected", INK)])
        style.configure(
            "Treeview.Heading", background=PAPER, foreground=MUTED, font=(family, 11), relief="flat", padding=(8, 6)
        )
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # 二重の枠線を消す

        for widget in ("TRadiobutton", "TCheckbutton"):
            style.configure(widget, background=PAPER, foreground=INK, indicatorcolor=SHEET)
            style.map(widget, indicatorcolor=[("selected", GREEN)], background=[("active", PAPER)])
        style.configure("TCombobox", fieldbackground=SHEET, background=SHEET, arrowcolor=INK, padding=4)
        style.map("TCombobox", fieldbackground=[("disabled", PAPER)], foreground=[("disabled", "#9AA7A4")])
        style.configure("TEntry", fieldbackground=SHEET, padding=4)
        style.configure(
            "Green.Horizontal.TProgressbar", troughcolor=RULE, background=GREEN, bordercolor=RULE, thickness=8
        )
        style.configure("Vertical.TScrollbar", background=PAPER, troughcolor=SHEET, arrowcolor=MUTED)

    # ---------- 画面の組み立て ----------

    def _build(self) -> None:
        main = ttk.Frame(self.root, padding=(24, 14, 24, 16))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        ttk.Label(main, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        upper = ttk.Frame(main)
        upper.grid(row=1, column=0, sticky="nsew")
        upper.columnconfigure(0, weight=1)
        upper.rowconfigure(0, weight=1)
        self._build_tray(upper).grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        self._build_output_settings(upper).grid(row=0, column=1, sticky="ns")
        self._build_menu()

        run = ttk.Frame(main)
        run.grid(row=2, column=0, sticky="ew", pady=(16, 14))
        run.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(run, text="文字起こしを開始", style="Primary.TButton", command=self.start)
        self.start_button.grid(row=0, column=0, rowspan=2)
        self.stop_button = ttk.Button(run, text="中止", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, rowspan=2, padx=(10, 18))
        self.progress = ttk.Progressbar(run, mode="determinate", style="Green.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=2, sticky="sew")
        self.status = tk.StringVar()
        ttk.Label(run, textvariable=self.status, style="Muted.TLabel").grid(row=1, column=2, sticky="nw", pady=(6, 0))

        self._build_result(main).grid(row=3, column=0, sticky="nsew")
        self._refresh_empty_state()

    def _build_tray(self, parent) -> ttk.Frame:
        """書類の一覧。スキャナの給紙トレイに見立て、空のときは全体が投入口になる。"""
        tray = ttk.Frame(parent)
        tray.columnconfigure(0, weight=1)
        tray.rowconfigure(1, weight=1)
        ttk.Label(tray, text="書類", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        sheet = tk.Frame(tray, background=SHEET, highlightthickness=1, highlightbackground=RULE)
        sheet.grid(row=1, column=0, sticky="nsew")
        sheet.columnconfigure(0, weight=1)
        sheet.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(sheet, columns=("status", "folder"), height=5, selectmode="extended")
        self.tree.heading("#0", text="ファイル", anchor="w")
        self.tree.heading("status", text="状態", anchor="w")
        self.tree.heading("folder", text="場所", anchor="w")
        self.tree.column("#0", width=220, stretch=False)
        self.tree.column("status", width=230, stretch=False)
        self.tree.column("folder", width=160, stretch=True)
        self.tree.tag_configure("done", foreground=GREEN)
        self.tree.tag_configure("error", foreground=RED)
        self.tree.tag_configure("busy", foreground=INK, font=(self.ui_family, 12, "bold"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(sheet, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_result())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected_output())
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())

        # 空のときに一覧の上に重ねる投入口 (点線の枠)
        self.empty_label = tk.Canvas(sheet, background=SHEET, highlightthickness=0, cursor="hand2")
        self.empty_label.bind("<Configure>", lambda _e: self._draw_empty_tray())
        self.empty_label.bind("<Button-1>", lambda _e: self.add_files())
        if self.dnd:
            for widget in (self.tree, self.empty_label):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        buttons = ttk.Frame(tray)
        buttons.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.add_files_button = ttk.Button(buttons, text="ファイルを追加…", command=self.add_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(buttons, text="フォルダを追加…", command=self.add_folder)
        self.add_folder_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(buttons, text="リストから外す", command=self.remove_selected)
        self.remove_button.pack(side="left")
        return tray

    def _draw_empty_tray(self) -> None:
        canvas = self.empty_label
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 40 or height < 40:
            return
        canvas.create_rectangle(14, 14, width - 14, height - 14, outline=GREEN, dash=(6, 5), width=2)
        main_text = "ここに書類をドラッグ" if self.dnd else "クリックして書類を選ぶ"
        canvas.create_text(width / 2, height / 2 - 14, text=main_text, fill=INK, font=(self.ui_family, 16, "bold"))
        canvas.create_text(
            width / 2, height / 2 + 18, text="JPG・PDF・PNG・TIFF", fill=MUTED, font=(self.ui_family, 11)
        )

    def _build_output_settings(self, parent) -> ttk.Frame:
        panel = ttk.Frame(parent, width=330)
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="保存する形式", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        # よく変える設定なので、ひと目で選べる大きな札にする
        self.format_var = tk.StringVar()
        self.format_tiles: dict[str, tk.Radiobutton] = {}
        tiles = ttk.Frame(panel)
        tiles.grid(row=1, column=0, sticky="ew")
        for column, (value, label) in enumerate(FORMAT_LABELS.items()):
            name, ext = label.replace(")", "").split(" (")
            tile = tk.Radiobutton(
                tiles,
                text=f"{name}\n{ext}",
                value=value,
                variable=self.format_var,
                command=self._sync_widgets,
                indicatoron=False,
                width=8,
                pady=10,
                relief="flat",
                offrelief="flat",
                borderwidth=0,
                highlightthickness=1,
                cursor="hand2",
                font=(self.ui_family, 13, "bold"),
            )
            tile.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
            tiles.columnconfigure(column, weight=1)
            self.format_tiles[value] = tile

        options = ttk.Frame(panel)
        options.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        options.columnconfigure(0, weight=1)

        def field(row: int, text: str) -> None:
            ttk.Label(options, text=text, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 3))

        # 「PDF の中身」と「文字コード」は同時には使わないので、同じ場所で切り替える
        self.detail_label = ttk.Label(options, style="Muted.TLabel")
        self.detail_label.grid(row=0, column=0, sticky="w", pady=(0, 3))
        self.pdf_mode_var = tk.StringVar()
        self.pdf_mode_box = ttk.Combobox(
            options, textvariable=self.pdf_mode_var, values=list(PDF_MODE_LABELS.values()), state="readonly"
        )
        self.pdf_mode_box.grid(row=1, column=0, sticky="ew")
        self.encoding_var = tk.StringVar()
        self.encoding_box = ttk.Combobox(
            options, textvariable=self.encoding_var, values=list(ENCODING_LABELS.values()), state="readonly"
        )
        self.encoding_box.grid(row=1, column=0, sticky="ew")

        field(2, "保存先")
        self.dest_mode = tk.StringVar()
        ttk.Radiobutton(
            options,
            text="元のファイルと同じフォルダ",
            value="same",
            variable=self.dest_mode,
            command=self._sync_widgets,
        ).grid(row=3, column=0, sticky="w")
        dest = ttk.Frame(options)
        dest.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        dest.columnconfigure(1, weight=1)
        ttk.Radiobutton(dest, text="指定", value="custom", variable=self.dest_mode, command=self._sync_widgets).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.output_dir_var = tk.StringVar()
        self.output_dir_entry = ttk.Entry(dest, textvariable=self.output_dir_var)
        self.output_dir_entry.grid(row=0, column=1, sticky="ew")
        self.output_dir_button = ttk.Button(dest, text="参照…", command=self.choose_output_dir)
        self.output_dir_button.grid(row=0, column=2, padx=(6, 0))

        # めったに変えない設定はメニュー「設定」に置く
        self.language_var = tk.StringVar()
        self.rotate_var = tk.BooleanVar()
        self.tesseract_var = tk.StringVar()
        return panel

    def _build_result(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.result_title = ttk.Label(header, text="結果", style="Heading.TLabel")
        self.result_title.grid(row=0, column=0, sticky="w")
        self.copy_button = ttk.Button(header, text="コピー", command=self.copy_text, state="disabled")
        self.copy_button.grid(row=0, column=1)
        self.open_button = ttk.Button(
            header, text="保存したファイルを開く", command=self.open_selected_output, state="disabled"
        )
        self.open_button.grid(row=0, column=2, padx=8)
        self.folder_button = ttk.Button(
            header, text="保存先フォルダを開く", command=self.open_selected_folder, state="disabled"
        )
        self.folder_button.grid(row=0, column=3)

        sheet = tk.Frame(frame, background=SHEET, highlightthickness=1, highlightbackground=RULE)
        sheet.grid(row=1, column=0, sticky="nsew")
        sheet.columnconfigure(0, weight=1)
        sheet.rowconfigure(0, weight=1)
        self.text = tk.Text(
            sheet,
            wrap="none",  # 折り返すと列がずれるので、コピーしたときと同じ並びで見せる
            height=8,
            font=(self.mono_family, 13),
            background=SHEET,
            foreground=INK,
            relief="flat",
            borderwidth=0,
            padx=16,
            pady=12,
            spacing1=2,
            spacing3=4,
            selectbackground=GREEN_PALE,
            selectforeground=INK,
            highlightthickness=0,
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(sheet, orient="vertical", command=self.text.yview)
        text_scroll.grid(row=0, column=1, sticky="ns")
        text_xscroll = ttk.Scrollbar(sheet, orient="horizontal", command=self.text.xview)
        text_xscroll.grid(row=1, column=0, sticky="ew")
        self.text.configure(yscrollcommand=text_scroll.set, xscrollcommand=text_xscroll.set, state="disabled")

        self.output_label = ttk.Label(frame, style="Muted.TLabel")
        self.output_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        return frame

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=False)
        language_menu = tk.Menu(settings_menu, tearoff=False)
        for label in LANGUAGES:
            language_menu.add_radiobutton(label=label, value=label, variable=self.language_var)
        settings_menu.add_cascade(label="書類の言語", menu=language_menu)
        settings_menu.add_checkbutton(label="横向き・逆さまのスキャンを自動で直す", variable=self.rotate_var)
        settings_menu.add_separator()
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
        for value, tile in self.format_tiles.items():
            selected = value == fmt
            tile.configure(
                background=GREEN if selected else SHEET,
                foreground="white" if selected else INK,
                activebackground=GREEN_DARK if selected else GREEN_PALE,
                activeforeground="white" if selected else INK,
                selectcolor=GREEN,
                highlightbackground=GREEN if selected else RULE,
                highlightcolor=INK,
            )
        self.pdf_mode_box.configure(state="readonly" if fmt == "pdf" else "disabled")
        self.encoding_box.configure(state="disabled" if fmt == "pdf" else "readonly")
        shown, hidden = (
            (self.pdf_mode_box, self.encoding_box) if fmt == "pdf" else (self.encoding_box, self.pdf_mode_box)
        )
        hidden.grid_remove()
        shown.grid()
        self.detail_label.configure(text="PDF の中身" if fmt == "pdf" else "文字コード")
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
            self.empty_label.place(relx=0, rely=0, relwidth=1, relheight=1)

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
                self.tree.item(item, tags=("busy",) if text.startswith("処理中") else ())
            if name:
                self.status.set(f"{name} を読み取っています")
        elif kind == "done":
            _, item, result = event
            self.results[item] = result
            if self.tree.exists(item):
                self.tree.set(item, "status", STATUS_DONE)
                self.tree.item(item, tags=("done",))
                self.tree.selection_set(item)
                self.tree.see(item)
        elif kind == "error":
            _, item, message = event
            if self.tree.exists(item):
                self.tree.set(item, "status", f"エラー: {message.splitlines()[0]}")
                self.tree.item(item, tags=("error",))
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
        self.result_title.configure(text=f"結果: {result.source.name}" if result else "結果")
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
