import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class FileToolbar(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_open: Callable[[], None],
        on_save: Callable[[], None],
        on_overwrite: Callable[[], None],
    ):
        super().__init__(parent, padding=(12, 12, 12, 0))
        ttk.Button(self, text="PDFを開く", width=0, command=on_open).pack(side="left")
        self.save_button = ttk.Button(
            self, text="別名保存", width=0, command=on_save, state="disabled"
        )
        self.save_button.pack(side="right")
        self.overwrite_button = ttk.Button(
            self, text="上書き保存", width=0, command=on_overwrite, state="disabled"
        )
        self.overwrite_button.pack(side="right", padx=(0, 6))
        self.filename = tk.StringVar(self, value="PDF未選択")
        ttk.Label(self, textvariable=self.filename).pack(side="left", padx=10)

    def set_save_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.save_button.configure(state=state)
        self.overwrite_button.configure(state=state)


class EditToolbar(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_mode_change: Callable[[], None],
        on_apply: Callable[[], None],
    ):
        super().__init__(parent, padding=(12, 8, 12, 4))
        self.columnconfigure(0, weight=1)
        self.modes = ttk.Frame(self)
        self.modes.grid(row=0, column=0, sticky="w")
        self.mode = tk.StringVar(self, value="text")
        for label, mode in (
            ("文字削除", "text"),
            ("選択範囲削除", "region"),
            ("要素削除", "element"),
        ):
            ttk.Radiobutton(
                self.modes,
                text=label,
                value=mode,
                variable=self.mode,
                command=on_mode_change,
            ).pack(side="left", padx=(0, 8))

        self.effects = ttk.Frame(self)
        self.effects.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.blackout = tk.BooleanVar(self)
        ttk.Checkbutton(self.effects, text="黒塗り", variable=self.blackout).pack(
            side="left", padx=(0, 8)
        )
        self.apply_button = ttk.Button(
            self.effects,
            text="プレビューに適用",
            width=0,
            command=on_apply,
            state="disabled",
        )
        self.apply_button.pack(side="left")
        self.effects_row = 0
        self.bind("<Configure>", self.reflow)

    def reflow(self, event):
        # Include the toolbar's side padding and the gap between the two groups.
        single_row_width = (
            self.modes.winfo_reqwidth() + self.effects.winfo_reqwidth() + 32
        )
        row = 0 if event.width >= single_row_width else 1
        if row == self.effects_row:
            return
        self.effects_row = row
        if row:
            self.effects.grid_configure(
                row=1, column=0, columnspan=2, padx=0, pady=(4, 0)
            )
        else:
            self.effects.grid_configure(
                row=0, column=1, columnspan=1, padx=(8, 0), pady=0
            )

    def set_apply_enabled(self, enabled: bool):
        self.apply_button.configure(state="normal" if enabled else "disabled")


class SearchToolbar(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_search: Callable[[], None],
        on_change: Callable[[], None],
    ):
        super().__init__(parent, padding=(12, 8))
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text="削除する文字列").grid(row=0, column=0)
        self.query = tk.StringVar(self)
        self.query.trace_add("write", lambda *_: on_change())
        self.entry = ttk.Entry(self, textvariable=self.query, font="TkTextFont")
        self.entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.entry.bind("<Return>", lambda event: on_search())
        self.match_mode = tk.StringVar(self, value="部分一致")
        self.match_mode.trace_add("write", lambda *_: on_change())
        ttk.Combobox(
            self,
            textvariable=self.match_mode,
            values=("部分一致", "単語全体"),
            font="TkTextFont",
            width=8,
            state="readonly",
        ).grid(row=0, column=2, padx=(0, 8))
        self.search_button = ttk.Button(
            self, text="検索", width=0, command=on_search, state="disabled"
        )
        self.search_button.grid(row=0, column=3)

    @property
    def whole_word(self) -> bool:
        return self.match_mode.get() == "単語全体"

    def enable_search(self):
        self.search_button.configure(state="normal")

    def set_query(self, text: str):
        self.query.set(text)
        self.entry.icursor("end")
        self.entry.focus_set()


class PageControls(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_navigate: Callable[[int], None],
        on_zoom: Callable[[int], None],
    ):
        super().__init__(parent, padding=(12, 8))
        self.columnconfigure(3, weight=1, minsize=16)
        self.previous = ttk.Button(
            self, text="前へ", width=0, command=lambda: on_navigate(-1)
        )
        self.previous.grid(row=0, column=0)
        self.page_label = ttk.Label(self, width=8, anchor="center")
        self.page_label.grid(row=0, column=1)
        self.following = ttk.Button(
            self, text="次へ", width=0, command=lambda: on_navigate(1)
        )
        self.following.grid(row=0, column=2)
        self.zoom_out = ttk.Button(self, text="-", width=0, command=lambda: on_zoom(-1))
        self.zoom_out.grid(row=0, column=4)
        self.zoom_label = ttk.Label(self, width=5, anchor="center")
        self.zoom_label.grid(row=0, column=5)
        self.zoom_in = ttk.Button(self, text="+", width=0, command=lambda: on_zoom(1))
        self.zoom_in.grid(row=0, column=6)
        self.fit_button = ttk.Button(
            self, text="リセット", width=0, command=lambda: on_zoom(0)
        )
        self.fit_button.grid(row=0, column=7, padx=(6, 0))
        self.status = tk.StringVar(self, value="編集するPDFを開いてください。")
        ttk.Label(self, textvariable=self.status).grid(
            row=1, column=0, columnspan=8, sticky="w", pady=(6, 0)
        )
        self.set_page(0, 0)
        self.set_zoom(None, can_zoom_out=False, can_zoom_in=False)

    def set_page(self, number: int, count: int):
        self.page_label.configure(text=f"{number + 1} / {count}" if count else "")
        self.previous.configure(state="normal" if number else "disabled")
        self.following.configure(state="normal" if number + 1 < count else "disabled")

    def set_zoom(self, percent: int | None, *, can_zoom_out: bool, can_zoom_in: bool):
        self.zoom_label.configure(text=f"{percent}%" if percent is not None else "")
        self.zoom_out.configure(state="normal" if can_zoom_out else "disabled")
        self.zoom_in.configure(state="normal" if can_zoom_in else "disabled")
        self.fit_button.configure(
            state="normal" if percent not in (None, 100) else "disabled"
        )
