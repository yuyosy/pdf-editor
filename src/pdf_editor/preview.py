import tkinter as tk
from collections.abc import Callable
from tkinter import font, ttk

import pymupdf

from .pdf_edits import Selection
from .pdf_elements import PageElement, area_affects, enclosing_rect, page_elements
from .text_selection import Caret, PageText, SelectedText

PREVIEW_MARGIN = 12
A4_HEIGHT_TO_WIDTH = 297 / 210
SEARCH_COLOR = "#a34b00"
REGION_COLOR = "#1559b7"
CANDIDATE_COLOR = "#687891"
AFFECTED_COLOR = "#00786e"
MIN_ZOOM_LEVEL = -4
MAX_ZOOM_LEVEL = 5
ZOOM_STEP = 1.25


class PdfPreview(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_select: Callable[[pymupdf.Rect, int | None], None],
        on_remove: Callable[[int], None],
        on_search_text: Callable[[str], None],
    ):
        super().__init__(parent)
        self.on_select = on_select
        self.on_remove = on_remove
        self.on_search_text = on_search_text
        self.page: pymupdf.Page | None = None
        self.mode = "text"
        self.zoom_level = 0
        self.scroll_width = self.scroll_height = 1
        self.matches: list[list[pymupdf.Rect]] = []
        self.selections: dict[int, Selection] = {}
        self.elements: list[PageElement] | None = None
        self.candidate_boxes: dict[int, pymupdf.Rect] = {}
        self.selected_boxes: dict[int, pymupdf.Rect] = {}
        self.menu_number: int | None = None
        self.preview: tk.PhotoImage | None = None
        self.page_to_canvas = pymupdf.Matrix(1, 1)
        self.drag_start: pymupdf.Point | None = None
        self.page_text: PageText | None = None
        self.text_anchor: Caret | None = None
        self.selected_text: SelectedText | None = None
        self.resize_job: str | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self, background="#e5e7eb", highlightthickness=0, cursor="xterm"
        )
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<MouseWheel>", self.scroll_preview)
        self.canvas.bind("<ButtonPress-1>", self.press_preview)
        self.canvas.bind("<B1-Motion>", self.drag_preview)
        self.canvas.bind("<ButtonRelease-1>", self.finish_drag)
        self.canvas.bind("<Button-3>", self.show_text_menu)
        self.canvas.bind("<Control-c>", self.copy_selected_text)
        self.canvas.bind("<Escape>", lambda event: self.cancel_selection())
        self.canvas.bind("<Motion>", self.hover_preview)
        self.canvas.bind("<Leave>", lambda event: self.hide_menu())
        self.canvas.bind("<Configure>", self.schedule_resize)
        self.text_menu = tk.Menu(self, tearoff=False, font="TkDefaultFont")
        self.text_menu.add_command(label="コピー", command=self.copy_selected_text)
        self.text_menu.add_command(
            label="検索欄に入れる", command=self.send_selected_text
        )

    def show_page(
        self,
        page: pymupdf.Page,
        matches: list[list[pymupdf.Rect]],
        selections: dict[int, Selection],
        *,
        mode: str,
        keep_scroll: bool = False,
    ):
        self.page = page
        self.elements = None
        self.page_text = None
        self.clear_text_selection()
        self.matches = matches
        self.selections = selections
        self.mode = mode
        self.canvas.configure(cursor="xterm" if mode == "text" else "")
        self.render(keep_scroll=keep_scroll)

    def set_marks(
        self, matches: list[list[pymupdf.Rect]], selections: dict[int, Selection]
    ):
        self.matches = matches
        self.selections = selections
        self.draw_marks()

    def reveal_matches(self):
        bounds = self.canvas.bbox("match")
        if bounds is not None:
            self.canvas.xview_moveto(max(0, bounds[0] - 24) / self.scroll_width)
            self.canvas.yview_moveto(max(0, bounds[1] - 24) / self.scroll_height)

    def scroll_preview(self, event):
        if self.canvas.yview() != (0.0, 1.0):
            self.hide_menu()
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    @property
    def zoom_factor(self) -> float:
        return ZOOM_STEP**self.zoom_level

    def zoom(self, direction: int):
        if self.page is None:
            return
        level = (
            max(MIN_ZOOM_LEVEL, min(MAX_ZOOM_LEVEL, self.zoom_level + direction))
            if direction
            else 0
        )
        if level == self.zoom_level:
            return
        center = pymupdf.Point(
            self.canvas.canvasx(self.canvas.winfo_width() / 2),
            self.canvas.canvasy(self.canvas.winfo_height() / 2),
        )
        focus = center * ~self.page_to_canvas
        self.zoom_level = level
        self.render(focus=focus)

    def schedule_resize(self, _event):
        if self.page is not None:
            if self.resize_job is not None:
                self.after_cancel(self.resize_job)
            self.resize_job = self.after(60, self.resize_preview)

    def resize_preview(self):
        self.resize_job = None
        self.render(keep_scroll=True)

    def render(self, *, keep_scroll: bool = False, focus: pymupdf.Point | None = None):
        if self.page is None:
            return
        page = self.page
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        padding = 2 * PREVIEW_MARGIN
        # Allow two points for rounded A4 dimensions in the PDF.
        fit_height = min(page.rect.height, page.rect.width * A4_HEIGHT_TO_WIDTH + 2)
        fit_scale = min(
            max(1, width - padding - 1) / page.rect.width,
            max(1, height - padding - 1) / fit_height,
            2,
        )
        scale = fit_scale * self.zoom_factor
        xview, yview = (
            (self.canvas.xview()[0], self.canvas.yview()[0]) if keep_scroll else (0, 0)
        )
        matrix = pymupdf.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB)
        self.preview = tk.PhotoImage(data=pixmap.tobytes("ppm"), format="PPM")
        self.cancel_region()
        self.text_anchor = None
        self.canvas.delete("all")
        left = max(PREVIEW_MARGIN, (width - pixmap.width) // 2)
        self.page_to_canvas = (
            page.rotation_matrix
            * matrix
            * pymupdf.Matrix(1, 0, 0, 1, left - pixmap.x, PREVIEW_MARGIN - pixmap.y)
        )
        self.canvas.create_image(
            left, PREVIEW_MARGIN, anchor="nw", image=self.preview, tags="page"
        )
        self.draw_candidates()
        self.draw_marks()
        self.draw_text_selection()
        self.scroll_width = max(width, pixmap.width + padding)
        self.scroll_height = max(height, pixmap.height + padding)
        self.canvas.configure(
            scrollregion=(0, 0, self.scroll_width, self.scroll_height)
        )
        if focus is not None:
            point = focus * self.page_to_canvas
            xview = max(0, point.x - width / 2) / self.scroll_width
            yview = max(0, point.y - height / 2) / self.scroll_height
        self.canvas.xview_moveto(xview)
        self.canvas.yview_moveto(yview)

    def draw_marks(self):
        self.hide_menu()
        self.canvas.delete("match", "selection")
        self.selected_boxes.clear()
        regions = [
            selection.bounds
            for selection in self.selections.values()
            if selection.element_index is None
        ]
        self.draw_region_elements(regions, "region-element")
        for glyphs in self.matches:
            rect = enclosing_rect(glyphs) * self.page_to_canvas
            self.canvas.create_rectangle(
                *rect, outline=SEARCH_COLOR, width=2, tags="match"
            )
        for number, selection in self.selections.items():
            rect = selection.bounds * self.page_to_canvas
            self.canvas.create_rectangle(
                *rect, outline=REGION_COLOR, width=2, tags="selection"
            )
            badge = self.label(rect.tl, str(number), REGION_COLOR, "selection")
            self.selected_boxes[number] = enclosing_rect((rect, badge))

    def label(
        self, point: pymupdf.Point, text: str, color: str, tag: str
    ) -> pymupdf.Rect:
        item = self.canvas.create_text(
            point.x + 5,
            point.y + 2,
            text=text,
            fill="white",
            anchor="nw",
            font="TkDefaultFont",
            tags=tag,
        )
        box = pymupdf.Rect(self.canvas.bbox(item)) + (-4, -2, 4, 2)
        background = self.canvas.create_rectangle(
            *box, fill=color, outline="", tags=tag
        )
        self.canvas.tag_lower(background, item)
        return box

    def draw_candidates(self):
        self.candidate_boxes.clear()
        self.canvas.delete("candidate")
        if self.page is None or self.mode != "element":
            return
        clip = pymupdf.Rect(self.canvas.bbox("page"))
        for index, element in enumerate(self.current_elements()):
            bounds = (element.bounds * self.page_to_canvas) & clip
            if not bounds.is_empty:
                self.candidate_boxes[index] = bounds
                self.canvas.create_rectangle(
                    *bounds, outline=CANDIDATE_COLOR, dash=(3, 3), tags="candidate"
                )

    def current_elements(self) -> list[PageElement]:
        if self.elements is None and self.page is not None:
            self.elements = page_elements(self.page)
        return self.elements or []

    def draw_region_elements(self, regions: list[pymupdf.Rect], tag: str):
        self.canvas.delete(tag)
        if not regions:
            return
        clip = pymupdf.Rect(self.canvas.bbox("page"))
        for element in self.current_elements():
            if any(area_affects(element, region) for region in regions):
                bounds = (element.bounds * self.page_to_canvas) & clip
                if not bounds.is_empty:
                    self.canvas.create_rectangle(
                        *bounds, outline=AFFECTED_COLOR, dash=(3, 2), tags=tag
                    )

    def set_mode(self, mode: str):
        self.mode = mode
        self.canvas.configure(cursor="xterm" if mode == "text" else "")
        self.cancel_selection()
        self.draw_candidates()
        self.draw_marks()

    def pointer(self, event) -> pymupdf.Point:
        return pymupdf.Point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def hide_menu(self):
        self.menu_number = None
        self.canvas.delete("selection-menu")

    def over_menu(self, point: pymupdf.Point) -> bool:
        bounds = self.canvas.bbox("selection-menu")
        return bool(bounds and pymupdf.Rect(bounds).contains(point))

    def hover_preview(self, event):
        point = self.pointer(event)
        menu = self.canvas.bbox("selection-menu")
        if menu is not None:
            near_menu = pymupdf.Rect(menu) + (-6, -6, 6, 6)
            if near_menu.contains(point):
                return
        number = next(
            (
                number
                for number, rect in reversed(self.selected_boxes.items())
                if rect.contains(point)
            ),
            None,
        )
        if number == self.menu_number:
            return
        self.hide_menu()
        if number is not None:
            self.menu_number = number
            # Keep the menu near the pointer even when the selected frame is partly offscreen.
            text = "選択枠を解除"
            label_width = font.nametofont("TkDefaultFont", root=self).measure(text) + 12
            right = self.canvas.canvasx(self.canvas.winfo_width())
            left = self.canvas.canvasx(0)
            x = (
                point.x + 6
                if point.x + label_width + 6 < right
                else max(left, point.x - label_width - 6)
            )
            y = min(point.y, self.canvas.canvasy(self.canvas.winfo_height()) - 25)
            self.label(pymupdf.Point(x, y), text, REGION_COLOR, "selection-menu")

    def press_preview(self, event):
        self.cancel_selection()
        bounds = self.canvas.bbox("page")
        point = self.pointer(event)
        if self.menu_number is not None and self.over_menu(point):
            self.on_remove(self.menu_number)
            return
        if bounds is None or not pymupdf.Rect(bounds).contains(point):
            return
        self.canvas.focus_set()
        if self.mode == "element":
            candidates = [
                index
                for index, rect in self.candidate_boxes.items()
                if rect.contains(point)
            ]
            if candidates:
                index = min(
                    candidates, key=lambda idx: self.candidate_boxes[idx].get_area()
                )
                self.on_select(
                    self.candidate_boxes[index] * ~self.page_to_canvas, index
                )
        elif self.mode == "region":
            self.hide_menu()
            self.drag_start = point
        elif self.mode == "text":
            self.hide_menu()
            self.start_text_selection(point)

    def start_text_selection(self, point: pymupdf.Point):
        if self.page is None:
            return
        if self.page_text is None:
            self.page_text = PageText(self.page)
        scale = max(abs(self.page_to_canvas.a), abs(self.page_to_canvas.b))
        self.text_anchor = self.page_text.caret_at(
            point * ~self.page_to_canvas, tolerance=8 / scale
        )

    def drag_preview(self, event):
        if self.text_anchor is not None and self.page_text is not None:
            end = self.page_text.caret_at(self.pointer(event) * ~self.page_to_canvas)
            if end is not None:
                self.selected_text = self.page_text.select(self.text_anchor, end)
                self.draw_text_selection()
        else:
            self.drag_region(event)

    def finish_drag(self, event):
        if self.text_anchor is None:
            self.finish_region(event)
            return
        self.drag_preview(event)
        self.text_anchor = None
        self.show_text_menu(event)

    def draw_text_selection(self):
        self.canvas.delete("text-selection")
        if self.selected_text is not None:
            clip = pymupdf.Rect(self.canvas.bbox("page"))
            for box in self.selected_text.boxes:
                bounds = (box * self.page_to_canvas) & clip
                if not bounds.is_empty:
                    self.canvas.create_rectangle(
                        *bounds,
                        fill="#6aa9ff",
                        stipple="gray50",
                        outline="",
                        tags="text-selection",
                    )

    def clear_text_selection(self):
        self.text_anchor = None
        self.selected_text = None
        self.canvas.delete("text-selection")

    def cancel_selection(self):
        self.cancel_region()
        self.clear_text_selection()

    def show_text_menu(self, event):
        if self.mode != "text" or self.selected_text is None:
            return
        self.text_menu.entryconfigure(
            1, state="normal" if len(self.selected_text.boxes) == 1 else "disabled"
        )
        self.text_menu.tk_popup(event.x_root, event.y_root)

    def copy_selected_text(self, _event=None):
        if self.selected_text is not None:
            self.clipboard_clear()
            self.clipboard_append(self.selected_text.text)
            return "break"

    def send_selected_text(self):
        if self.selected_text is not None and len(self.selected_text.boxes) == 1:
            text = self.selected_text.text
            self.clear_text_selection()
            self.on_search_text(text)

    def drag_bounds(self, event) -> pymupdf.Rect:
        box = pymupdf.Rect(self.drag_start, self.pointer(event)).normalize()
        return box & pymupdf.Rect(self.canvas.bbox("page"))

    def drag_region(self, event):
        if self.drag_start is None:
            return
        box = self.drag_bounds(event)
        self.canvas.delete("drag")
        self.draw_region_elements(
            [box * ~self.page_to_canvas] if not box.is_empty else [], "drag-element"
        )
        self.canvas.create_rectangle(
            *box, outline=REGION_COLOR, dash=(4, 3), width=2, tags="drag"
        )

    def finish_region(self, event):
        if self.drag_start is None:
            return
        box = self.drag_bounds(event)
        self.cancel_region()
        if box.width >= 4 and box.height >= 4:
            self.on_select(box * ~self.page_to_canvas, None)

    def cancel_region(self):
        self.drag_start = None
        self.canvas.delete("drag", "drag-element")
