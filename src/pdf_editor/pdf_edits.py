import os
import re
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from pymupdf import mupdf

from .pdf_elements import (
    PageElement,
    center_rect,
    enclosing_rect,
    isolated_rect,
    page_elements,
    text_lines,
)

WORD_JOINERS = "[-.@+'’]"
Matches = dict[int, list[list[pymupdf.Rect]]]


@dataclass(frozen=True)
class Selection:
    page: int
    bounds: pymupdf.Rect
    element_index: int | None = None


class ElementRemovalError(ValueError):
    def __init__(self, page_number: int):
        super().__init__(
            f"{page_number + 1}ページ目で、選択した画像・図形を個別に削除できません。\n"
            "重なっている内容も消す場合は、選択枠を外してから「選択範囲削除」を使ってください。"
        )


def open_pdf(data: bytes) -> pymupdf.Document:
    document = pymupdf.open(stream=data, filetype="pdf")
    if not document.is_pdf or document.needs_pass or not document.page_count:
        document.close()
        raise ValueError(
            "ページのある、パスワード保護されていないPDFを選んでください。"
        )
    return document


def find_text(
    document: pymupdf.Document, query: str, *, whole_word: bool = False
) -> Matches:
    if not query:
        return {}
    pattern = re.escape(query)
    if whole_word:
        # Join punctuation only between word characters, so a final period stays a delimiter.
        if not query[0].isspace():
            pattern = rf"(?<!\w)(?<!\w{WORD_JOINERS}){pattern}"
        if not query[-1].isspace():
            pattern += rf"(?!\w|{WORD_JOINERS}\w)"
    matcher = re.compile(pattern)
    matches: Matches = {}
    for number in range(document.page_count):
        page = document.load_page(number)
        for chars in text_lines(page):
            text = "".join(char["c"] for char in chars)
            for match in matcher.finditer(text):
                rects = [
                    pymupdf.Rect(char["bbox"])
                    for char in chars[match.start() : match.end()]
                ]
                matches.setdefault(number, []).append(rects)
    return matches


def rect_coordinates(rect: pymupdf.Rect) -> tuple[float, float, float, float]:
    return rect.x0, rect.y0, rect.x1, rect.y1


def removal_rects(
    page: pymupdf.Page, number: int, targets: list[pymupdf.Rect]
) -> Iterable[pymupdf.Rect]:
    # Small rectangles inside each glyph avoid touching adjacent glyphs.
    all_rects = [
        pymupdf.Rect(char["bbox"]) for line in text_lines(page) for char in line
    ]
    for target in {rect_coordinates(rect): rect for rect in targets}.values():
        if target.is_empty:
            raise ValueError(
                f"{number + 1}ページ目の文字の位置を取得できませんでした。"
            )
        area = center_rect(target)
        if sum(area.intersects(rect) for rect in all_rects) != sum(
            area.intersects(rect) for rect in targets
        ):
            raise ValueError(
                f"{number + 1}ページ目では他の文字と重なるため、削除を中止しました。"
            )
        yield area


def apply_removal(
    page: pymupdf.Page,
    areas: Iterable[pymupdf.Rect],
    *,
    blackout: bool = False,
    **options,
):
    # An empty color sequence leaves the redacted area unfilled.
    fill = (0, 0, 0) if blackout else ()
    for area in areas:
        page.add_redact_annot(area, fill=fill, cross_out=False)
    page.apply_redactions(**options)


def remove_elements(
    page: pymupdf.Page, number: int, elements: list[PageElement], selected: set[int]
):
    visible_page = page.rect * page.derotation_matrix
    for kind in ("image", "drawing"):
        targets = [
            element
            for index, element in enumerate(elements)
            if index in selected and element.kind == kind
        ]
        if not targets:
            continue
        remaining = [
            element
            for index, element in enumerate(elements)
            if index not in selected and element.kind == kind
        ]
        blockers = [element.removal_bounds for element in remaining]
        covered = []
        touched = []
        for element in targets:
            bounds = element.removal_bounds
            if kind == "drawing":
                padded = bounds + (-0.25, -0.25, 0.25, 0.25)
                if not any(padded.contains(blocker) for blocker in blockers):
                    covered.append(padded)
                    continue
            area = isolated_rect(bounds & visible_page, blockers)
            if area is None:
                raise ElementRemovalError(number)
            touched.append(area)
        if covered:
            apply_removal(
                page,
                covered,
                images=mupdf.PDF_REDACT_IMAGE_NONE,
                graphics=mupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=mupdf.PDF_REDACT_TEXT_NONE,
            )
        if touched:
            apply_removal(
                page,
                touched,
                images=mupdf.PDF_REDACT_IMAGE_REMOVE
                if kind == "image"
                else mupdf.PDF_REDACT_IMAGE_NONE,
                graphics=mupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED
                if kind == "drawing"
                else mupdf.PDF_REDACT_LINE_ART_NONE,
                text=mupdf.PDF_REDACT_TEXT_NONE,
            )
        expected = Counter(rect_coordinates(element.bounds) for element in remaining)
        actual = Counter(
            rect_coordinates(element.bounds)
            for element in page_elements(page)
            if element.kind == kind
        )
        if actual != expected:
            raise ElementRemovalError(number)


def apply_edits(
    data: bytes,
    query: str,
    selections: Iterable[Selection],
    *,
    whole_word: bool = False,
    blackout: bool = False,
) -> bytes:
    with open_pdf(data) as document:
        matches = find_text(document, query, whole_word=whole_word)
        by_page: dict[int, list[Selection]] = {}
        for selection in selections:
            by_page.setdefault(selection.page, []).append(selection)
        if not (matches or by_page):
            raise ValueError("削除する文字列、要素、または範囲を指定してください。")
        for number in sorted(matches.keys() | by_page.keys()):
            page = document[number]
            if next(page.annots(types=[mupdf.PDF_ANNOT_REDACT]), None) is not None:
                raise ValueError(
                    f"{number + 1}ページ目に未適用の削除マークがあります。"
                )
            chosen = by_page.get(number, [])
            page_matches = matches.get(number, [])
            indices = {
                selection.element_index
                for selection in chosen
                if selection.element_index is not None
            }
            shapes = page_elements(page) if indices else []
            selected_glyphs = Counter(
                rect_coordinates(rect)
                for index in indices
                for rect in shapes[index].glyphs
            )
            searched_glyphs = Counter(
                rect_coordinates(rect) for group in page_matches for rect in group
            )
            if glyphs := selected_glyphs | searched_glyphs:
                apply_removal(
                    page,
                    removal_rects(
                        page, number, [pymupdf.Rect(rect) for rect in glyphs.elements()]
                    ),
                    images=mupdf.PDF_REDACT_IMAGE_NONE,
                    graphics=mupdf.PDF_REDACT_LINE_ART_NONE,
                )
            if indices:
                remove_elements(page, number, shapes, indices)
            if areas := [
                selection.bounds
                for selection in chosen
                if selection.element_index is None
            ]:
                apply_removal(
                    page,
                    areas,
                    images=mupdf.PDF_REDACT_IMAGE_PIXELS,
                    graphics=mupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                    blackout=blackout,
                )
            if blackout:
                # Paint the complete visual boxes after removing the targeted glyphs or elements.
                covers = [enclosing_rect(group) for group in page_matches]
                covers.extend(
                    choice.bounds
                    for choice in chosen
                    if choice.element_index is not None
                )
                visible_page = page.rect * page.derotation_matrix
                for bounds in covers:
                    area = bounds & visible_page
                    if not area.is_empty:
                        page.draw_rect(area, color=None, fill=(0, 0, 0), overlay=True)

        result = document.tobytes(garbage=4, deflate=True)
    if matches:
        with open_pdf(result) as edited:
            if find_text(edited, query, whole_word=whole_word):
                raise ValueError("削除結果に検索した文字列が残っています。")
    return result


def save_edited(
    data: bytes,
    query: str,
    selections: Iterable[Selection],
    source: Path,
    destination: Path,
    *,
    whole_word: bool = False,
    overwrite: bool = False,
    blackout: bool = False,
) -> bytes:
    if not overwrite and (
        destination.resolve() == source.resolve()
        or (source.exists() and destination.exists() and source.samefile(destination))
    ):
        raise ValueError("元のPDFとは異なるファイル名を指定してください。")

    selections = list(selections)
    result = (
        apply_edits(data, query, selections, whole_word=whole_word, blackout=blackout)
        if query or selections
        else data
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".pdf", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(result)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result
