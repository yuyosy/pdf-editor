from dataclasses import dataclass
from math import hypot

import pymupdf

from .pdf_elements import enclosing_rect, text_line_data

Caret = tuple[int, int]


@dataclass(frozen=True)
class SelectedText:
    text: str
    boxes: list[pymupdf.Rect]


@dataclass(frozen=True)
class TextLine:
    bounds: pymupdf.Rect
    glyphs: list[tuple[str, pymupdf.Rect]]
    direction: pymupdf.Point

    def distance_to(self, point: pymupdf.Point) -> float:
        dx = max(self.bounds.x0 - point.x, point.x - self.bounds.x1, 0)
        dy = max(self.bounds.y0 - point.y, point.y - self.bounds.y1, 0)
        return hypot(dx, dy)

    def caret_at(self, point: pymupdf.Point) -> int:
        along_line = point.x * self.direction.x + point.y * self.direction.y
        for index, (_, box) in enumerate(self.glyphs):
            center = (box.tl + box.br) / 2
            if along_line < center.x * self.direction.x + center.y * self.direction.y:
                return index
        return len(self.glyphs)


class PageText:
    def __init__(self, page: pymupdf.Page):
        self.lines: list[TextLine] = []
        for line in text_line_data(page):
            glyphs = [
                (char["c"], pymupdf.Rect(char["bbox"]))
                for span in line["spans"]
                for char in span["chars"]
            ]
            if glyphs:
                self.lines.append(
                    TextLine(
                        pymupdf.Rect(line["bbox"]), glyphs, pymupdf.Point(line["dir"])
                    )
                )

    def caret_at(
        self, point: pymupdf.Point, *, tolerance: float | None = None
    ) -> Caret | None:
        if not self.lines:
            return None
        index, line = min(
            enumerate(self.lines), key=lambda item: item[1].distance_to(point)
        )
        if tolerance is not None and line.distance_to(point) > tolerance:
            return None
        return index, line.caret_at(point)

    def select(self, anchor: Caret, end: Caret) -> SelectedText | None:
        (first, start), (last, stop) = sorted((anchor, end))
        lines = []
        boxes = []
        for index in range(first, last + 1):
            glyphs = self.lines[index].glyphs
            left = start if index == first else 0
            right = stop if index == last else len(glyphs)
            part = glyphs[left:right]
            if part:
                lines.append("".join(char for char, _ in part))
                boxes.append(enclosing_rect(rect for _, rect in part))
        return SelectedText("\n".join(lines), boxes) if lines else None
