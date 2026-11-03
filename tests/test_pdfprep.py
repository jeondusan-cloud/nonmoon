import json

import pymupdf
import pytest

from nonmoon import pdfprep


def test_parse_pages():
    assert pdfprep.parse_pages(None, 5) == [0, 1, 2, 3, 4]
    assert pdfprep.parse_pages("1-2,5", 5) == [0, 1, 4]
    assert pdfprep.parse_pages("4-", 5) == [3, 4]
    with pytest.raises(ValueError):
        pdfprep.parse_pages("6", 5)


def test_prepare_writes_pages_text_and_info(paper, tmp_path):
    work = tmp_path / "work"
    info = pdfprep.prepare(paper, work)
    assert info["page_count"] == 2
    for suffix in ("", "-top", "-bot", "-grid"):
        assert (work / "pages" / f"p001{suffix}.png").is_file()
    assert "Abstract" in (work / "text" / "p001.txt").read_text(encoding="utf-8")
    assert [c["label"] for c in info["captions"]] == ["FIG. 1"]
    assert info["pages"][0]["graphics"], "the vector figure should be detected"
    assert json.loads((work / "info.json").read_text(encoding="utf-8"))["source"] == "paper.pdf"


def test_prepare_page_range(paper, tmp_path):
    info = pdfprep.prepare(paper, tmp_path / "w", pages="2")
    assert info["page_count"] == 1 and info["page_numbers_in_original"] == [2]
    with pymupdf.open(tmp_path / "w" / "source.pdf") as doc:
        assert "THEORY" in doc[0].get_text()


def test_figure_box_snaps_to_drawing(paper, tmp_path):
    pdfprep.prepare(paper, tmp_path / "w")
    with pymupdf.open(tmp_path / "w" / "source.pdf") as doc:
        page = doc[0]
        # A rough box that cuts off the right part of the drawn frame.
        rough = [100 / 595, 150 / 842, 400 / 595, 380 / 842]
        rect = pdfprep.figure_rect(page, rough)
        assert rect.x1 >= 480 and rect.y1 >= 380
        assert rect.y1 < 405, "the caption below must stay out"
        data, mime = pdfprep.crop(doc, 1, rough)
    assert mime == "image/png" and data[:4] == b"\x89PNG"


def test_figure_box_keeps_captions_and_text_out():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # A page-wide frame that also encloses the caption (Polish "Rys." label).
    page.draw_rect(pymupdf.Rect(40, 100, 555, 520), color=(0.8, 0.8, 0.8), width=0.5)
    page.draw_rect(pymupdf.Rect(150, 120, 440, 440), color=(0, 0, 0), width=1)
    page.draw_line((160, 430), (430, 130), color=(0, 0, 1), width=1.5)
    page.insert_text((60, 480), "Rys. 2. A framed figure whose caption sits inside the frame.", fontsize=10)
    # A left-column drawing that spills into the gutter, beside a right-column paragraph.
    page.draw_rect(pymupdf.Rect(60, 600, 312, 760), color=(0, 0, 0), width=1)
    paragraph = "Right column text that runs on for several lines, so it is clearly a paragraph of the body. " * 3
    page.insert_textbox(pymupdf.Rect(306, 600, 540, 760), paragraph, fontsize=10)

    framed = pdfprep.figure_rect(page, [150 / 595, 120 / 842, 440 / 595, 440 / 842])
    assert framed.x0 > 100, "the page frame must not be followed"
    assert framed.y1 < 470, "the caption must stay out"
    spilling = pdfprep.figure_rect(page, [60 / 595, 600 / 842, 300 / 595, 760 / 842])
    assert 300 <= spilling.x1 <= 306, "the crop stops before the neighbouring column"
    assert pdfprep.CAPTION_RE.match("Rys. 15. Transmission")


def test_figure_images_writes_files(paper, tmp_path):
    pdfprep.prepare(paper, tmp_path / "w")
    figures = [{"id": "fig1", "page": 1, "bbox": [0.15, 0.17, 0.82, 0.46]}, {"id": "fig9", "page": 9, "bbox": []}]
    uris = pdfprep.figure_images(tmp_path / "w", figures, save_dir=tmp_path / "w" / "figures")
    assert list(uris) == ["fig1"]
    assert uris["fig1"].startswith("data:image/png;base64,")
    assert (tmp_path / "w" / "figures" / "fig1.png").is_file()
