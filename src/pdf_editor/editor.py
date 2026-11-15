import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import pymupdf

from .controls import EditToolbar, FileToolbar, PageControls, SearchToolbar
from .pdf_edits import Matches, Selection, apply_edits, find_text, open_pdf, save_edited
from .preview import MAX_ZOOM_LEVEL, MIN_ZOOM_LEVEL, PdfPreview


class Editor(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root)
        self.root = root
        self.source: Path | None = None
        self.data = b""
        self.document: pymupdf.Document | None = None
        self.has_applied_changes = False
        self.page_number = 0
        self.matches: Matches = {}
        self.selections: dict[int, Selection] = {}
        self.next_number = 1

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.files = FileToolbar(self, self.open_file, self.save, self.overwrite)
        self.files.grid(row=0, column=0, sticky="ew")
        self.actions = EditToolbar(self, self.change_mode, self.apply)
        self.actions.grid(row=1, column=0, sticky="ew")
        self.search_bar = SearchToolbar(self, self.search, self.clear_search)
        self.search_bar.grid(row=2, column=0, sticky="ew")
        self.mode_hint = ttk.Label(self, padding=(12, 0), anchor="w")
        self.mode_hint.grid(row=2, column=0, sticky="nsew")
        self.mode_hint.grid_remove()
        self.preview = PdfPreview(
            self, self.add_selection, self.remove_selection, self.search_bar.set_query
        )
        self.preview.grid(row=3, column=0, sticky="nsew", padx=12)
        self.pages = PageControls(self, self.go, self.zoom)
        self.pages.grid(row=4, column=0, sticky="ew")

    def open_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, filetypes=[("PDF", "*.pdf")]
        )
        if path:
            self.load(Path(path))

    def load(self, source: Path):
        data = source.read_bytes()
        document = open_pdf(data)
        self.update_idletasks()
        self.replace_document(data, document)
        self.source = source
        self.page_number = 0
        self.has_applied_changes = False
        self.matches.clear()
        self.selections.clear()
        self.next_number = 1
        self.preview.zoom_level = 0
        self.files.filename.set(source.name)
        self.search_bar.enable_search()
        self.show_page()
        self.update_selection()

    def replace_document(self, data: bytes, document: pymupdf.Document):
        if self.document is not None:
            self.document.close()
        self.data, self.document = data, document

    def page_selections(self) -> dict[int, Selection]:
        return {
            number: selection
            for number, selection in self.selections.items()
            if selection.page == self.page_number
        }

    def show_page(self, *, keep_scroll: bool = False):
        if self.document is not None:
            self.preview.show_page(
                self.document[self.page_number],
                self.matches.get(self.page_number, []),
                self.page_selections(),
                mode=self.actions.mode.get(),
                keep_scroll=keep_scroll,
            )
            self.pages.set_page(self.page_number, self.document.page_count)
            self.update_zoom()

    def go(self, direction: int):
        self.page_number += direction
        self.show_page()

    def change_mode(self):
        mode = self.actions.mode.get()
        self.rowconfigure(2, minsize=self.search_bar.winfo_reqheight())
        if mode == "text":
            self.mode_hint.grid_remove()
            self.search_bar.grid()
        else:
            self.search_bar.grid_remove()
            self.mode_hint.configure(
                text=(
                    "削除する要素の枠をクリックしてください。"
                    if mode == "element"
                    else "プレビュー上で削除する範囲をドラッグしてください。"
                )
            )
            self.mode_hint.grid()
        self.preview.set_mode(mode)
        self.update_selection()

    def zoom(self, direction: int):
        self.preview.zoom(direction)
        if self.document is not None:
            self.update_zoom()

    def update_zoom(self):
        self.pages.set_zoom(
            round(self.preview.zoom_factor * 100),
            can_zoom_out=self.preview.zoom_level > MIN_ZOOM_LEVEL,
            can_zoom_in=self.preview.zoom_level < MAX_ZOOM_LEVEL,
        )

    def add_selection(self, bounds: pymupdf.Rect, element_index: int | None):
        if element_index is not None and any(
            choice.element_index == element_index
            for choice in self.page_selections().values()
        ):
            return
        self.selections[self.next_number] = Selection(
            self.page_number, bounds, element_index
        )
        self.next_number += 1
        self.refresh_marks()
        self.update_selection()

    def remove_selection(self, number: int):
        del self.selections[number]
        self.refresh_marks()
        self.update_selection()

    def refresh_marks(self):
        self.preview.set_marks(
            self.matches.get(self.page_number, []), self.page_selections()
        )

    def clear_search(self):
        self.matches.clear()
        self.refresh_marks()
        self.update_selection()

    def update_selection(self, *, searched: bool = False):
        pending = bool(self.matches or self.selections)
        self.actions.set_apply_enabled(pending)
        self.files.set_save_enabled(pending or self.has_applied_changes)
        if self.document is None:
            return
        count = sum(len(groups) for groups in self.matches.values())
        if pending or searched:
            self.pages.status.set(
                f"検索結果 {count} 件  ／  選択枠 {len(self.selections)} 件"
            )
        elif self.has_applied_changes:
            self.pages.status.set("未保存の編集があります。")
        elif self.actions.mode.get() == "text":
            self.pages.status.set("プレビュー上の文字もドラッグして選べます。")
        else:
            self.pages.status.set("")

    def search(self):
        if self.document is None:
            return
        query = self.search_bar.query.get()
        self.matches = find_text(
            self.document, query, whole_word=self.search_bar.whole_word
        )
        if self.matches:
            self.page_number = next(iter(self.matches))
            self.show_page()
            self.preview.reveal_matches()
        else:
            self.refresh_marks()
        self.update_selection(searched=bool(query))

    def save(self):
        if self.source is None or not (
            self.matches or self.selections or self.has_applied_changes
        ):
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            filetypes=[("PDF", "*.pdf")],
            defaultextension=".pdf",
            initialdir=self.source.parent,
            initialfile=f"{self.source.stem}_edited.pdf",
        )
        if path:
            destination = Path(path)
            self.save_to(destination)
            self.pages.status.set(f"保存しました  {destination.name}")

    def overwrite(self):
        if self.source is None or not (
            self.matches or self.selections or self.has_applied_changes
        ):
            return
        data = self.save_to(self.source.resolve(), overwrite=True)
        self.finish_edit(data, unsaved=False)
        self.pages.status.set(f"上書き保存しました  {self.source.name}")

    def save_to(self, destination: Path, *, overwrite: bool = False) -> bytes:
        assert self.source is not None
        return save_edited(
            self.data,
            self.search_bar.query.get() if self.matches else "",
            self.selections.values(),
            self.source,
            destination,
            whole_word=self.search_bar.whole_word,
            overwrite=overwrite,
            blackout=self.actions.blackout.get(),
        )

    def apply(self):
        if self.document is None or not (self.matches or self.selections):
            return
        query = self.search_bar.query.get() if self.matches else ""
        data = apply_edits(
            self.data,
            query,
            self.selections.values(),
            whole_word=self.search_bar.whole_word,
            blackout=self.actions.blackout.get(),
        )
        self.finish_edit(data, unsaved=True)
        self.pages.status.set(
            "プレビューに適用しました。続けて編集するか保存できます。"
        )

    def finish_edit(self, data: bytes, *, unsaved: bool):
        self.replace_document(data, open_pdf(data))
        self.has_applied_changes = unsaved
        self.selections.clear()
        self.matches.clear()
        self.show_page(keep_scroll=True)
        self.update_selection()
