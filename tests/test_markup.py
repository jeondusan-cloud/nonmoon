from nonmoon import markup
from nonmoon.markup import Linker, render, render_inline, repair_tex_escapes


def test_inline_and_display_math():
    html = render("에너지 $E = h\\nu$ 이다.\n\n$$\\frac{a}{b}$$")
    assert '<span class="math-inline" data-tex="E = h\\nu">' in html
    assert '<div class="math-block"><span class="math-display" data-tex="\\frac{a}{b}">' in html


def test_dollar_rules():
    # A literal \$ and a price are not math; math needs no space inside the dollars.
    html = render_inline("비용은 \\$5 이고 $x$ 와 $ y $")
    assert html.count("math-inline") == 1
    assert "$5" in html and "$ y $" in html


def test_html_is_escaped_everywhere():
    html = render("<script>alert(1)</script> **<b>** $<x>$")
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html
    assert 'data-tex="&lt;x&gt;"' in html


def test_lists_paragraphs_and_formatting():
    html = render("머리말\n- 하나 **굵게**\n- 둘 *기울임*\n  이어지는 줄\n\n1. 첫째\n2. 둘째")
    assert html.startswith("<p>머리말</p><ul><li>하나 <strong>굵게</strong></li>")
    assert "<li>둘 <em>기울임</em> 이어지는 줄</li>" in html
    assert "<ol><li>첫째</li><li>둘째</li></ol>" in html


def test_citations_and_links():
    html = render_inline("참고 [3–8], [2, 11] 와 [링크](https://doi.org/10.1/x)")
    assert html.count('class="cite"') == 2
    assert '<a href="https://doi.org/10.1/x" target="_blank" rel="noopener">링크</a>' in html
    assert "href" not in render_inline("[x](javascript:alert(1))")


def test_terms_link_once_per_scope_and_refs():
    linker = Linker(
        [{"en": "optical pumping", "ko": "광펌핑", "definition": ""}],
        figures={"2": "fig-fig2"},
        equations={"3": "eq-3"},
    )
    first = render("광펌핑은 그림 2와 식 (3)에서 보듯 광펌핑이다.", linker)
    assert first.count('class="term"') == 1
    assert 'href="#fig-fig2"' in first and 'href="#eq-3"' in first
    assert 'class="term"' not in render("광펌핑", linker)
    linker.new_scope()
    assert 'class="term"' in render("광펌핑", linker)
    en = render("Optical pumping, see Fig. 2(b).", linker, english=True)
    assert 'class="term"' in en and 'href="#fig-fig2"' in en


def test_unknown_refs_stay_plain():
    linker = Linker([], figures={"1": "fig-fig1"})
    assert "xref" not in render_inline("그림 7을 보라", linker)


def test_repair_tex_escapes():
    broken = "식 $\x0crac{1}{2} + \x08eta + \tau + \nu + \rho$ 그리고\nusing"
    fixed = repair_tex_escapes(broken)
    assert fixed == "식 $\\frac{1}{2} + \\beta + \\tau + \\nu + \\rho$ 그리고\nusing"
    assert repair_tex_escapes("\x0crac{a}{b}", math_only=False) == "\\frac{a}{b}"


def test_plain_strips_markup():
    assert markup.plain("**굵게** `코드` [글](https://a.b)") == "굵게 코드 글"
