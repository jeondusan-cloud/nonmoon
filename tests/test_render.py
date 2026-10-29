import json
import re
from pathlib import Path

from nonmoon import book as books
from nonmoon.render import KATEX_CDN, render_book

FIXTURE = Path(__file__).parent / "fixtures" / "sample"


def _data(html: str) -> dict:
    raw = re.search(r'<script type="application/json" id="book-data">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw)


def test_standalone_is_a_full_offline_document():
    b = books.validate(books.load(FIXTURE))
    html = render_book(b, {}, artifact=False, profile="p")
    assert html.startswith("<!doctype html>")
    assert "katex.min.js" not in html and "renderToString" in html  # KaTeX inlined
    assert "data:font/woff2;base64," in html
    assert 'data-act="print"' in html
    assert "<title>포화 흡수 분광 노트</title>" in html
    assert "ask" not in _data(html)


def test_artifact_fragment_follows_the_page_contract():
    b = books.validate(books.load(FIXTURE))
    html = render_book(b, {}, artifact=True, profile="중성원자 연구실 학생")
    assert html.lstrip().startswith("<title>")
    for tag in ("<!doctype", "<html", "<head>", "<body"):
        assert tag not in html.lower()
    assert f'<script src="{KATEX_CDN}">' in html
    external = re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    assert external and all(u.startswith("https://fonts.googleapis.com/") for u in external)
    assert 'data-act="print"' not in html
    data = _data(html)
    assert data["ask"]["profile"] == "중성원자 연구실 학생"
    assert "b1-1" in data["ask"]["blocks"]
    assert data["ask"]["blocks"]["b1-3"]["kind"] == "equation"


def test_content_lands_in_the_page():
    b = books.validate(books.load(FIXTURE))
    html = render_book(b, {"fig1": "data:image/png;base64,AAAA"}, artifact=False)
    assert 'id="s-s1"' in html and 'id="s-s2"' in html and 'id="eq-1"' in html
    assert 'id="fig-fig1"' in html and 'src="data:image/png;base64,AAAA"' in html
    assert '<span class="eq-no">' not in html and '<div class="eq-no">(1)</div>' in html
    assert "note--lab" in html and "실험실 노트" in html
    assert 'href="#fig-fig1"' in html  # "그림 1" became a link
    assert html.count('<details><summary>풀이 보기</summary>') == 1


def test_unplaced_figure_goes_after_first_mention():
    b = books.validate(books.load(FIXTURE))
    b["sections"][0]["blocks"] = [x for x in b["sections"][0]["blocks"] if x["type"] != "figure"]
    html = render_book(b, {}, artifact=False)
    first_para = html.index('id="b1-1"')
    assert first_para < html.index('id="fig-fig1"') < html.index('id="eq-1"')


def test_korean_source_has_no_translation_controls():
    b = books.validate(books.load(FIXTURE))
    b["meta"]["source_language"] = "ko"
    html = render_book(b, {}, artifact=False)
    assert 'data-set-mode="both"' not in html
    assert '"translated":false' in html


def test_script_data_cannot_close_its_tag():
    b = books.validate(books.load(FIXTURE))
    b["glossary"][0]["definition"] = "</script><script>alert(1)</script>"
    html = render_book(b, {}, artifact=True)
    raw = re.search(r'<script type="application/json" id="book-data">(.*?)</script>', html, re.S).group(1)
    assert "</script" not in raw
    assert _data(html)["glossary"][0]["def"].startswith("<p>&lt;/script&gt;")
