import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).parent))


def make_paper(path: Path) -> Path:
    """A two-page born-digital 'paper' with a vector figure and a caption."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "A Short Test Paper", fontsize=16)
    page.insert_text((72, 110), "Abstract. We test the pipeline with a tiny document.", fontsize=10)
    page.draw_rect(pymupdf.Rect(100, 150, 480, 380), color=(0, 0, 0), width=1)
    page.draw_line((120, 360), (460, 170), color=(0.1, 0.2, 0.8), width=1.5)
    page.insert_text((250, 375), "x (MHz)", fontsize=9)
    page.insert_text((72, 410), "FIG. 1. A straight line in a box.", fontsize=10)
    page.insert_text((72, 450), "I. INTRODUCTION  Body text refers to Fig. 1 and Eq. (1).", fontsize=10)
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 80), "II. THEORY  More body text on the second page.", fontsize=10)
    doc.save(path)
    return path


@pytest.fixture
def paper(tmp_path) -> Path:
    return make_paper(tmp_path / "paper.pdf")
