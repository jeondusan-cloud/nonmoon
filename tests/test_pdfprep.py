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


def test_figure_images_writes_files(paper, tmp_path):
    pdfprep.prepare(paper, tmp_path / "w")
    figures = [{"id": "fig1", "page": 1, "bbox": [0.15, 0.17, 0.82, 0.46]}, {"id": "fig9", "page": 9, "bbox": []}]
    uris = pdfprep.figure_images(tmp_path / "w", figures, save_dir=tmp_path / "w" / "figures")
    assert list(uris) == ["fig1"]
    assert uris["fig1"].startswith("data:image/png;base64,")
    assert (tmp_path / "w" / "figures" / "fig1.png").is_file()
