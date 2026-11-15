import tkinter as tk
import traceback
from functools import partial
from tkinter import font, messagebox, ttk
from types import TracebackType

from .editor import Editor
from .pdf_edits import ElementRemovalError
from .preview import A4_HEIGHT_TO_WIDTH


def configure_window(root: tk.Tk):
    families = set(font.families(root))
    family = next(
        (name for name in ("Meiryo UI", "Noto Sans JP") if name in families), None
    )
    for name in ("TkDefaultFont", "TkTextFont"):
        ui_font = font.nametofont(name, root=root)
        ui_font.configure(family=family or ui_font.actual("family"), size=11)
    style = ttk.Style(root)
    style.configure("TLabel", font="TkDefaultFont")
    style.configure("TButton", font="TkDefaultFont", padding=(8, 4))

    root.title("PDFエディタ")
    height = min(
        1080,
        root.winfo_screenheight() - 96,
        round((root.winfo_screenwidth() - 48) * A4_HEIGHT_TO_WIDTH),
    )
    width = round(height / A4_HEIGHT_TO_WIDTH)
    root.geometry(f"{width}x{height}")
    root.minsize(min(width, 460), 400)


def report_callback_error(
    root: tk.Tk,
    error_type: type[BaseException],
    error: BaseException,
    trace: TracebackType | None,
):
    if not isinstance(error, ElementRemovalError):
        traceback.print_exception(error_type, error, trace)
    messagebox.showerror("操作を完了できませんでした", str(error), parent=root)


def main():
    root = tk.Tk()
    root.report_callback_exception = partial(report_callback_error, root)
    configure_window(root)
    Editor(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
