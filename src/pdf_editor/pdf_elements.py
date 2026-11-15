from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import pymupdf


@dataclass(frozen=True)
class PageElement:
    kind: Literal["text", "image", "drawing"]
    bounds: pymupdf.Rect
    removal_bounds: pymupdf.Rect
    glyphs: tuple[pymupdf.Rect, ...] = ()


def text_line_data(page: pymupdf.Page):
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    text_page = page.get_textpage(flags=flags)
    for block in text_page.extractRAWDICT()["blocks"]:
        yield from block.get("lines", [])


def text_lines(page: pymupdf.Page):
    for line in text_line_data(page):
        yield [char for span in line["spans"] for char in span["chars"]]


def enclosing_rect(rects: Iterable[pymupdf.Rect]) -> pymupdf.Rect:
    bounds = pymupdf.Rect()
    for rect in rects:
        bounds.include_rect(rect)
    return bounds


def page_elements(page: pymupdf.Page) -> list[PageElement]:
    elements: list[PageElement] = []
    for line in text_lines(page):
        glyphs = tuple(
            rect
            for char in line
            if char["c"].strip() and not (rect := pymupdf.Rect(char["bbox"])).is_empty
        )
        if glyphs:
            bounds = enclosing_rect(glyphs)
            elements.append(PageElement("text", bounds, bounds, glyphs))
    for info in page.get_image_info():
        bounds = pymupdf.Rect(info["bbox"])
        if not bounds.is_empty:
            elements.append(PageElement("image", bounds, bounds))
    boxes = page.get_bboxlog()
    for shape in page.get_cdrawings() or ():
        bounds = pymupdf.Rect(shape["rect"])
        margin = max(1.5, (shape.get("width") or 0) / 2)
        outline = bounds + (-margin, -margin, margin, margin)
        sequence = shape["seqno"]
        removal = pymupdf.Rect(boxes[sequence][1])
        # A filled and stroked path has separate bounding boxes in the display list.
        if (
            shape["type"] == "fs"
            and sequence + 1 < len(boxes)
            and boxes[sequence + 1][0] == "stroke-path"
        ):
            removal.include_rect(pymupdf.Rect(boxes[sequence + 1][1]))
        elements.append(PageElement("drawing", outline, removal))
    return elements


def area_affects(element: PageElement, area: pymupdf.Rect) -> bool:
    if element.kind == "drawing":
        return area.contains(element.removal_bounds)
    if not area.intersects(element.bounds):
        return False
    return element.kind == "image" or any(
        area.intersects(glyph) for glyph in element.glyphs
    )


def center_rect(target: pymupdf.Rect) -> pymupdf.Rect:
    x, y = (target.tl + target.br) / 2
    half_width = min(0.05, target.width / 4)
    half_height = min(0.05, target.height / 4)
    return pymupdf.Rect(
        x - half_width, y - half_height, x + half_width, y + half_height
    )


def isolated_rect(
    bounds: pymupdf.Rect, blockers: Iterable[pymupdf.Rect]
) -> pymupdf.Rect | None:
    if bounds.is_empty:
        return None
    overlapping = [blocker for blocker in blockers if bounds.intersects(blocker)]
    center = center_rect(bounds)
    if not any(center.intersects(blocker) for blocker in overlapping):
        return center

    # Split the rectangle around each blocker to find a patch unique to this element.
    free = [bounds]
    for blocker in overlapping:
        pieces = []
        for rect in free:
            overlap = rect & blocker
            if overlap.is_empty:
                pieces.append(rect)
                continue
            pieces.extend(
                piece for piece in (
                    pymupdf.Rect(rect.x0, rect.y0, rect.x1, overlap.y0),
                    pymupdf.Rect(rect.x0, overlap.y1, rect.x1, rect.y1),
                    pymupdf.Rect(rect.x0, overlap.y0, overlap.x0, overlap.y1),
                    pymupdf.Rect(overlap.x1, overlap.y0, rect.x1, overlap.y1),
                ) if not piece.is_empty
            )
        if not pieces:
            return None
        free = pieces
    return center_rect(max(free, key=lambda rect: rect.get_area()))
