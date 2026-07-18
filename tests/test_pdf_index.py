from buxter.pdf_index import (
    Occurrence,
    PageText,
    TextSpan,
    cluster_occurrences,
    detect_sheet_metadata,
    exclude_zones,
    find_occurrences,
    render_drawings_md,
    DrawingSetIndex,
)


def _span(text: str, x: float, y: float, w: float = 30.0, h: float = 10.0) -> TextSpan:
    return TextSpan(text=text, x0=x, top=y, x1=x + w, bottom=y + h)


def _page(spans: list[TextSpan], *, file: str = "set.pdf", page: int = 1,
          width: float = 1000.0, height: float = 700.0, raw_text: str | None = None) -> PageText:
    if raw_text is None:
        raw_text = " ".join(s.text for s in spans)
    return PageText(file=file, pdf_page=page, width=width, height=height,
                    spans=spans, raw_text=raw_text)


# --- sheet metadata ----------------------------------------------------------

def test_western_sheet_number_from_title_block() -> None:
    page = _page([
        _span("FOUNDATION", 100, 100),
        _span("S-101", 920, 660),  # title block, bottom-right
        _span("Rev.", 920, 675),
        _span("2", 955, 675),
    ], raw_text="FOUNDATION PLAN " + "x" * 40)
    record = detect_sheet_metadata(page)
    assert record.sheet_no == "S-101"
    assert record.discipline == "Structural"
    assert record.revision == "2"


def test_body_cross_reference_does_not_beat_title_block() -> None:
    page = _page([
        _span("SEE", 100, 50),
        _span("S-201", 140, 50),   # cross-reference in the drawing body
        _span("A-101", 920, 660),  # the sheet's own number in the title block
    ], raw_text="body " + "x" * 40)
    record = detect_sheet_metadata(page)
    assert record.sheet_no == "A-101"
    assert record.discipline == "Architectural"


def test_gost_mark_and_sheet() -> None:
    page = _page([
        _span("КЖ", 900, 650),
        _span("Лист", 900, 665),
        _span("5", 940, 665),
        _span("Изм.", 900, 680),
        _span("1", 940, 680),
    ], raw_text="ПЛАН ФУНДАМЕНТОВ " + "x" * 40)
    record = detect_sheet_metadata(page)
    assert record.sheet_no == "КЖ, лист 5"
    assert record.discipline == "Конструкции железобетонные"
    assert record.revision == "1"


def test_undetected_fields_stay_none() -> None:
    page = _page([_span("nothing", 10, 10)], raw_text="")
    record = detect_sheet_metadata(page)
    assert record.sheet_no is None
    assert record.revision is None
    assert record.discipline is None
    assert record.needs_ocr is True


# --- search & counting -------------------------------------------------------

def test_find_occurrences_with_coordinates() -> None:
    pages = [_page([_span("W1", 100, 100), _span("W1", 500, 300), _span("W2", 200, 200)])]
    hits = find_occurrences(pages, "W1")
    assert len(hits) == 2
    assert {(round(h.x), round(h.y)) for h in hits} == {(115, 105), (515, 305)}


def test_cluster_merges_fragmented_tag() -> None:
    # "W1" and its multiplier "2x" 10pt apart = one instance; the far hit is another.
    occs = [
        Occurrence("W1", "set.pdf", 1, 100, 100),
        Occurrence("W1", "set.pdf", 1, 110, 105),
        Occurrence("W1", "set.pdf", 1, 400, 400),
    ]
    clusters = cluster_occurrences(occs, radius=18.0)
    assert len(clusters) == 2


def test_cluster_never_merges_across_pages() -> None:
    occs = [
        Occurrence("P1", "set.pdf", 1, 100, 100),
        Occurrence("P1", "set.pdf", 2, 100, 100),
    ]
    assert len(cluster_occurrences(occs, radius=50.0)) == 2


def test_exclude_zones_drops_legend_hits() -> None:
    occs = [
        Occurrence("W1", "set.pdf", 1, 50, 50),    # legend
        Occurrence("W1", "set.pdf", 1, 500, 500),  # real instance
    ]
    kept = exclude_zones(occs, [("set.pdf", 1, 0, 0, 200, 200)])
    assert len(kept) == 1
    assert kept[0].x == 500


# --- registry rendering ------------------------------------------------------

def test_render_drawings_md_lists_pages_and_status() -> None:
    index = DrawingSetIndex()
    good = _page([_span("S-101", 920, 660)], raw_text="x" * 50)
    scanned = _page([], page=2, raw_text="")
    index.pages = [good, scanned]
    index.sheets = [detect_sheet_metadata(good), detect_sheet_metadata(scanned)]
    index.errors = ["broken.pdf: PDFSyntaxError: oops"]

    text = render_drawings_md(index)
    assert "| set.pdf | 1 | S-101 |" in text
    assert "OCR/визуальная проверка" in text
    assert "текстовый слой OK" in text
    assert "broken.pdf: PDFSyntaxError: oops" in text
