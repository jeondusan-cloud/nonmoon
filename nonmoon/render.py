"""Book -> one self-contained HTML textbook.

Two flavours share all markup:

* ``standalone``: a complete HTML document for opening from disk. KaTeX is
  inlined, so math renders offline, and a print button is offered.
* ``artifact``: a page fragment for publishing as a claude.ai Artifact. The
  host adds the document skeleton, scripts may only come from allow-listed
  CDNs and stylesheets only from Google Fonts, so KaTeX's script is loaded
  from jsDelivr while its CSS and fonts are inlined. Inside the Claude
  viewer the page can also ask Claude about any paragraph (``sample``).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import json
import re
from functools import lru_cache
from pathlib import Path

from . import __version__, schema
from .book import translated
from .markup import Linker, plain, render as md, render_inline as md1

ASSETS = Path(__file__).parent / "assets"
KATEX_VERSION = "0.16.22"
KATEX_CDN = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist/katex.min.js"
FONTS_CSS = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700"
    "&family=Noto+Serif+KR:wght@400;600;700&family=STIX+Two+Text:ital,wght@0,400;0,600;1,400&display=swap"
)


def e(text) -> str:
    return html.escape(str(text or ""), quote=True)


@lru_cache(maxsize=1)
def katex_css() -> str:
    """KaTeX's stylesheet with its fonts embedded as data: URIs."""
    css = (ASSETS / "katex" / "katex.min.css").read_text(encoding="utf-8")

    def embed(match: re.Match) -> str:
        font = (ASSETS / "katex" / "fonts" / f"{match.group(1)}.woff2").read_bytes()
        return 'src:url(data:font/woff2;base64,' + base64.b64encode(font).decode("ascii") + ') format("woff2")'

    return re.sub(
        r'src:url\(fonts/([A-Za-z0-9_-]+)\.woff2\) format\("woff2"\)(?:,url\([^)]*\) format\("[a-z]+"\))*',
        embed,
        css,
    )


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _script_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _anchor(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or "x"


class _Renderer:
    def __init__(self, book: dict, figures: dict[str, str], *, artifact: bool, profile: str, source_name: str):
        self.book = book
        self.images = figures
        self.artifact = artifact
        self.profile = profile
        self.source_name = source_name
        self.translated = translated(book)
        self.ask_blocks: dict[str, dict] = {}

        fig_numbers = {}
        for fig in book["figures"]:
            number = re.search(r"\d+", fig["label_original"] or fig["label"] or fig["id"])
            if number:
                fig_numbers[number.group(0)] = "fig-" + _anchor(fig["id"])
        eq_numbers = {}
        for _, block in self._blocks():
            if block["type"] == "equation" and block["number"]:
                eq_numbers[block["number"]] = "eq-" + _anchor(block["number"])
        self.linker = Linker(book["glossary"], fig_numbers, eq_numbers)
        self.figures_by_id = {f["id"]: f for f in book["figures"]}
        self.placement = self._place_figures()

    def _blocks(self):
        for section in self.book["sections"]:
            for block in section["blocks"]:
                yield section, block

    # Figures that no figure block places go after the block that first
    # mentions them, else at the end of the last section.
    def _place_figures(self) -> dict[tuple[int, int], list[str]]:
        placed = {b["id"] for _, b in self._blocks() if b["type"] == "figure"}
        extra: dict[tuple[int, int], list[str]] = {}
        for fig in self.book["figures"]:
            if fig["id"] in placed:
                continue
            number = re.search(r"\d+", fig["label_original"] or fig["label"] or fig["id"])
            pattern = re.compile(rf"(그림|Fig\.?|FIG\.?|Figure)\s?{number.group(0)}(?!\d)") if number else None
            spot = None
            for si, section in enumerate(self.book["sections"]):
                for bi, block in enumerate(section["blocks"]):
                    text = " ".join(str(block.get(k, "")) for k in ("original", "translation"))
                    if pattern and pattern.search(text):
                        spot = (si, bi)
                        break
                if spot:
                    break
            if spot is None and self.book["sections"]:
                spot = (len(self.book["sections"]) - 1, len(self.book["sections"][-1]["blocks"]) - 1)
            if spot:
                extra.setdefault(spot, []).append(fig["id"])
        return extra

    # --- pieces ---------------------------------------------------------------

    def tools(self, show_orig: bool, ask: bool = True) -> str:
        buttons = []
        if show_orig:
            buttons.append('<button type="button" class="tool" data-act="orig" aria-pressed="false">원문</button>')
        if ask and self.artifact:
            buttons.append('<button type="button" class="tool" data-act="ask" aria-expanded="false">질문</button>')
        return f'<div class="blk-tools">{"".join(buttons)}</div>' if buttons else ""

    def notes(self, notes: list[dict]) -> str:
        return "".join(self.note(n) for n in notes)

    def note(self, note: dict, extra_class: str = "") -> str:
        kind = note["kind"] if note["kind"] in schema.NOTE_KINDS else "concept"
        title = f'<span class="note-title">{md1(note["title"], self.linker)}</span>' if note["title"] else ""
        return (
            f'<aside class="note note--{kind} {extra_class}"><div class="note-head">'
            f'<span class="note-kind">{schema.NOTE_KIND_LABELS[kind]}</span>{title}</div>'
            f'<div class="note-body">{md(note["body"], self.linker)}</div></aside>'
        )

    def remember(self, blk: str, section: dict, kind: str, text: str) -> None:
        if self.artifact:
            self.ask_blocks[blk] = {"sec": section["id"], "kind": kind, "text": text.strip()[:6000]}

    @staticmethod
    def _notes_text(notes: list[dict]) -> str:
        return "".join(f"\n해설({n['title']}): {plain(n['body'])}" for n in notes)

    def paragraph(self, blk: str, section: dict, b: dict) -> str:
        has_tr = self.translated and b["translation"].strip()
        if has_tr:
            body = (
                f'<div class="orig" lang="en">{md(b["original"], self.linker, english=True)}</div>'
                f'<div class="tr" lang="ko">{md(b["translation"], self.linker)}</div>'
            )
        else:
            # A Korean paper, or a passage left untranslated: show it in every mode.
            lang = "ko" if not self.translated else "en"
            cls = "tr" if not self.translated else "orig keep"
            body = f'<div class="{cls}" lang="{lang}">{md(b["original"] or b["translation"], self.linker, english=lang == "en")}</div>'
        self.remember(
            blk,
            section,
            "paragraph",
            (f"원문: {b['original']}\n번역: {b['translation']}" if has_tr else b["original"] or b["translation"])
            + self._notes_text(b["notes"]),
        )
        return (
            f'<div class="blk para" id="{blk}" data-blk="{blk}"><div class="para-text">{body}</div>'
            f'{self.tools(bool(has_tr))}<div class="notes">{self.notes(b["notes"])}</div></div>'
        )

    def equation(self, blk: str, section: dict, b: dict) -> str:
        anchor = f'eq-{_anchor(b["number"])}' if b["number"] else blk
        number = f'<div class="eq-no">({e(b["number"])})</div>' if b["number"] else '<div class="eq-no"></div>'
        explain = ""
        if b["explanation"].strip() or b["symbols"]:
            rows = "".join(
                f'<tr><td class="sym"><span class="math-inline" data-tex="{e(s["symbol"])}">{e(s["symbol"])}</span></td>'
                f'<td>{md1(s["meaning"], self.linker)}</td></tr>'
                for s in b["symbols"]
            )
            table = f'<table class="symbols">{rows}</table>' if rows else ""
            explain = (
                f'<div class="eq-explain"><div class="label">수식 풀이</div>'
                f'{md(b["explanation"], self.linker)}{table}</div>'
            )
        self.remember(
            blk,
            section,
            "equation",
            f"식 ({b['number']}): $$ {b['latex']} $$\n풀이: {plain(b['explanation'])}"
            + "".join(f"\n기호 {s['symbol']}: {plain(s['meaning'])}" for s in b["symbols"])
            + self._notes_text(b["notes"]),
        )
        return (
            f'<div class="blk eq" id="{anchor}" data-blk="{blk}"><div class="eq-row"><div class="eq-math">'
            f'<span class="math-display" data-tex="{e(b["latex"])}">{e(b["latex"])}</span></div>{number}</div>'
            f'{explain}{self.tools(False)}<div class="notes">{self.notes(b["notes"])}</div></div>'
        )

    def figure(self, blk: str, section: dict, fig_id: str) -> str:
        fig = self.figures_by_id.get(fig_id)
        if not fig:
            return ""
        src = self.images.get(fig_id)
        img = (
            f'<img src="{src}" alt="{e(fig["label"])}" loading="lazy">'
            if src
            else f'<div class="fig-missing">그림 이미지를 만들지 못했습니다 (원문 {fig["page"]}쪽).</div>'
        )
        cap_ko = fig["caption_ko"].strip() if self.translated else ""
        main = md1(cap_ko or fig["caption_original"], self.linker, english=not cap_ko and self.translated)
        orig = (
            f'<div class="fig-orig" lang="en">{md1(fig["caption_original"], self.linker, english=True)}</div>'
            if cap_ko and fig["caption_original"]
            else ""
        )
        explain = (
            f'<div class="fig-explain note note--intuition"><div class="note-head"><span class="note-kind">그림 읽기</span></div>'
            f'<div class="note-body">{md(fig["explanation"], self.linker)}</div></div>'
            if fig["explanation"].strip()
            else ""
        )
        self.remember(
            blk,
            section,
            "figure",
            f"{fig['label']} 캡션: {fig['caption_original']}\n번역: {fig['caption_ko']}\n그림 읽기: {plain(fig['explanation'])}",
        )
        return (
            f'<figure class="blk fig" id="fig-{_anchor(fig_id)}" data-blk="{blk}"><div class="fig-img">{img}</div>'
            f'<figcaption><div class="cap-main{" has-orig" if orig else ""}"><span class="fig-label">{e(fig["label"])}</span>{main}</div>'
            f"{orig}</figcaption>{explain}{self.tools(False)}</figure>"
        )

    def table(self, blk: str, section: dict, b: dict) -> str:
        head = "".join(f"<th>{md1(h, self.linker)}</th>" for h in b["header"])
        rows = "".join("<tr>" + "".join(f"<td>{md1(c, self.linker)}</td>" for c in row) + "</tr>" for row in b["rows"])
        caption = b["caption_ko"] if self.translated and b["caption_ko"] else b["caption_original"]
        self.remember(
            blk,
            section,
            "table",
            f"표: {caption}\n" + " | ".join(b["header"]) + "\n" + "\n".join(" | ".join(r) for r in b["rows"]),
        )
        return (
            f'<div class="blk table" id="{blk}" data-blk="{blk}">'
            f'<div class="table-cap">{md1(caption, self.linker)}</div>'
            f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
            f'{self.tools(False)}<div class="notes">{self.notes(b["notes"])}</div></div>'
        )

    def heading(self, b: dict) -> str:
        ko = b["ko"].strip() if self.translated else ""
        main = e(ko or b["original"])
        orig = f'<span class="h-orig h-orig-inline">{e(b["original"])}</span>' if ko and b["original"] else ""
        return f'<h3 class="subhead">{main}{orig}</h3>'

    def block(self, si: int, bi: int, section: dict, b: dict) -> str:
        blk = f"b{si + 1}-{bi + 1}"
        kind = b["type"]
        if kind == "paragraph":
            out = self.paragraph(blk, section, b)
        elif kind == "equation":
            out = self.equation(blk, section, b)
        elif kind == "figure":
            out = self.figure(blk, section, b["id"])
        elif kind == "table":
            out = self.table(blk, section, b)
        elif kind == "note":
            out = f'<div class="blk" id="{blk}">{self.note(b)}</div>'
        elif kind == "heading":
            out = self.heading(b)
        else:
            out = ""
        for n, fig_id in enumerate(self.placement.get((si, bi), [])):
            out += self.figure(f"{blk}-f{n + 1}", section, fig_id)
        return out

    # --- chapters ---------------------------------------------------------------

    def cover(self) -> str:
        m = self.book["meta"]
        title = m["title_ko"] or m["title"]
        orig = f'<p class="cover-orig" lang="en">{e(m["title"])}</p>' if self.translated and m["title"] and m["title"] != title else ""
        venue_bits = [x for x in (m["venue"] or m["year"],) if x]
        kind = f'<span class="kind">{e(m["kind"])}</span>' if m["kind"] else ""
        venue = f'<p class="cover-venue">{kind}{e(" · ".join(venue_bits))}</p>' if (kind or venue_bits) else ""
        doi = (
            f' · <a href="https://doi.org/{e(m["doi"])}" target="_blank" rel="noopener">doi:{e(m["doi"])}</a>'
            if m["doi"]
            else ""
        )
        authors = f'<p class="cover-authors">{e(", ".join(m["authors"]))}{doi}</p>' if m["authors"] or doi else ""
        lede = (
            f'<p class="cover-lede">{md1(self.book["intro"]["one_line"])}</p>' if self.book["intro"]["one_line"] else ""
        )
        return f'<header class="cover col">{venue}<h1>{e(title)}</h1>{orig}{authors}{lede}</header>'

    def intro(self) -> str:
        i = self.book["intro"]
        self.linker.new_scope()
        parts = []
        if i["overview"]:
            parts.append(f'<h3 class="intro-h">한눈에 보기</h3><div class="prose">{md(i["overview"], self.linker)}</div>')
        if i["why_it_matters"]:
            parts.append(f'<h3 class="intro-h">왜 중요한가</h3><div class="prose">{md(i["why_it_matters"], self.linker)}</div>')
        if i["learning_goals"]:
            goals = "".join(f"<li>{md1(g, self.linker)}</li>" for g in i["learning_goals"])
            parts.append(f'<h3 class="intro-h">이 글을 읽고 나면</h3><ul class="goals prose">{goals}</ul>')
        if i["prerequisites"]:
            cards = "".join(
                f'<div class="prereq"><h4>{md1(p["title"])}</h4><div class="prose">{md(p["body"], self.linker)}</div></div>'
                for p in i["prerequisites"]
            )
            parts.append(f'<h3 class="intro-h">미리 알아둘 개념</h3><div class="prereqs">{cards}</div>')
        if i["reading_guide"]:
            parts.append(f'<h3 class="intro-h">읽는 방법</h3><div class="prose">{md(i["reading_guide"], self.linker)}</div>')
        if not parts:
            return ""
        return (
            '<section class="chapter col" id="intro"><div class="chapter-head"><div class="chapter-num">0</div>'
            f'<h2>들어가기 전에</h2></div>{"".join(parts)}</section>'
        )

    def section(self, si: int, s: dict) -> str:
        self.linker.new_scope()
        title = (s["title_ko"] if self.translated else "") or s["title"] or s["title_ko"]
        orig = f'<div class="h-orig" lang="en">{e(s["title"])}</div>' if self.translated and s["title"] and s["title"] != title else ""
        number = f'<div class="chapter-num">{e(s["number"])}</div>' if s["number"] else '<div class="chapter-num"></div>'
        summary = (
            f'<div class="box sec-summary"><div class="label">이 절의 요지</div>{md(s["summary"], self.linker)}</div>'
            if s["summary"].strip()
            else ""
        )
        blocks = "".join(self.block(si, bi, s, b) for bi, b in enumerate(s["blocks"]))
        keys = ""
        if s["key_points"]:
            items = "".join(f"<li>{md1(k, self.linker)}</li>" for k in s["key_points"])
            keys = f'<div class="box keypoints"><div class="label">핵심 정리</div><ul class="prose">{items}</ul></div>'
        return (
            f'<section class="chapter col" id="s-{_anchor(s["id"])}"><div class="chapter-head">{number}'
            f'<h2>{e(title)}</h2>{orig}</div>{summary}{blocks}{keys}</section>'
        )

    def wrap(self) -> str:
        sm = self.book["summary"]
        self.linker.new_scope()
        parts = []
        if sm["key_points"]:
            items = "".join(f"<li>{md1(k, self.linker)}</li>" for k in sm["key_points"])
            parts.append(f'<h3 class="intro-h">핵심 정리</h3><ul class="goals prose">{items}</ul>')
        if sm["questions"]:
            qs = "".join(
                f'<div class="question"><div class="prose"><span class="q-label">문제 {n}</span>{md(q["q"], self.linker)}</div>'
                f'<details><summary>풀이 보기</summary><div class="answer prose">{md(q["a"], self.linker)}</div></details></div>'
                for n, q in enumerate(sm["questions"], 1)
            )
            parts.append(f'<h3 class="intro-h" id="questions">확인 문제</h3><div class="questions">{qs}</div>')
        if self.book["glossary"]:
            rows = "".join(
                f'<div class="gl"><div class="gl-ko">{e(g["ko"])}<span class="gl-en" lang="en">{e(g["en"])}</span></div>'
                f'<div class="gl-def prose">{md(g["definition"])}</div></div>'
                for g in sorted(self.book["glossary"], key=lambda g: g["ko"])
            )
            parts.append(f'<h3 class="intro-h" id="glossary">용어 정리</h3><div class="glossary">{rows}</div>')
        if sm["further_reading"]:
            items = "".join(
                f'<li><span class="refs">{md1(r["ref"])}</span><div class="prose">{md(r["why"], self.linker)}</div></li>'
                for r in sm["further_reading"]
            )
            parts.append(f'<h3 class="intro-h">더 읽을거리</h3><ul class="reading">{items}</ul>')
        if self.book["references"]:
            refs = "".join(f"<li>{md1(r)}</li>" for r in self.book["references"])
            parts.append(
                f'<details class="refs" id="references"><summary>원문 참고문헌 {len(self.book["references"])}개</summary>'
                f"<ol>{refs}</ol></details>"
            )
        if self.artifact:
            parts.append('<div id="ask-global" data-blk="global" hidden><h3 class="intro-h">더 궁금한 점</h3></div>')
        if not parts:
            return ""
        return (
            '<section class="chapter col" id="wrap"><div class="chapter-head"><div class="chapter-num">✓</div>'
            f'<h2>정리와 확인</h2></div>{"".join(parts)}</section>'
        )

    def toc(self) -> str:
        items = []
        if any(self.book["intro"][k] for k in ("overview", "why_it_matters", "learning_goals", "prerequisites")):
            items.append('<li><a href="#intro"><span class="toc-num">0</span><span>들어가기 전에</span></a></li>')
        for s in self.book["sections"]:
            title = (s["title_ko"] if self.translated else "") or s["title"] or s["title_ko"]
            items.append(
                f'<li><a href="#s-{_anchor(s["id"])}"><span class="toc-num">{e(s["number"])}</span>'
                f"<span>{e(title)}</span></a></li>"
            )
        items.append('<li><a href="#wrap"><span class="toc-num">✓</span><span>정리와 확인</span></a></li>')
        return f'<nav class="toc" id="toc" aria-label="목차"><div class="toc-title">목차</div><ol>{"".join(items)}</ol></nav>'

    def topbar(self) -> str:
        m = self.book["meta"]
        modes = ""
        if self.translated:
            modes = (
                '<div class="seg" role="group" aria-label="보기 방식">'
                '<button type="button" data-set-mode="ko" aria-pressed="true">번역</button>'
                '<button type="button" data-set-mode="both" aria-pressed="false">대역</button>'
                '<button type="button" data-set-mode="en" aria-pressed="false">원문</button></div>'
            )
        print_btn = "" if self.artifact else '<button type="button" class="tb-btn" data-act="print">인쇄</button>'
        return (
            '<header class="topbar">'
            '<button type="button" class="tb-btn toc-btn" data-act="toc" aria-controls="toc" aria-expanded="false">목차</button>'
            f'<div class="tb-title">{e(m["short_title"] or m["title_ko"] or m["title"])}</div>'
            '<button type="button" class="tb-btn menu-btn" data-act="menu">보기</button>'
            f'<div class="tb-controls">{modes}'
            '<button type="button" class="tb-btn" data-act="notes" aria-pressed="true">해설</button>'
            '<button type="button" class="tb-btn" data-act="font">명조</button>'
            '<button type="button" class="tb-btn" data-act="smaller" aria-label="글자 작게">가−</button>'
            '<button type="button" class="tb-btn" data-act="larger" aria-label="글자 크게">가+</button>'
            f"{print_btn}</div>"
            '<div class="progress" aria-hidden="true"><span></span></div></header>'
        )

    def colophon(self, generated: str) -> str:
        source = f"원문 파일: {e(self.source_name)} · " if self.source_name else ""
        return (
            '<footer class="colophon col">AI(Claude)가 만든 번역과 해설입니다. 수식·수치·인용은 원문으로 꼭 확인하세요.<br>'
            f"{source}만든 날: {e(generated)} · nonmoon {__version__}</footer>"
        )

    def data(self, book_id: str) -> dict:
        glossary = [
            {"en": g["en"], "ko": g["ko"], "def": md(g["definition"])} for g in self.book["glossary"]
        ]
        out = {"id": book_id, "translated": self.translated, "glossary": glossary}
        if self.artifact:
            m, i = self.book["meta"], self.book["intro"]
            sections = {
                s["id"]: {"title": (s["title_ko"] or s["title"]), "summary": plain(s["summary"])}
                for s in self.book["sections"]
            }
            overview = "\n".join(
                [
                    f"한 줄 요약: {i['one_line']}",
                    f"개요: {plain(i['overview'])}",
                    "절별 요지:",
                    *[f"- {v['title']}: {v['summary']}" for v in sections.values()],
                    "핵심 정리:",
                    *[f"- {k}" for k in self.book["summary"]["key_points"]],
                    "용어: " + "; ".join(f"{g['ko']}({g['en']})" for g in self.book["glossary"]),
                ]
            )
            out["ask"] = {
                "profile": " ".join(self.profile.split())[:1500],
                "paper": f"{m['title_ko'] or m['title']} ({m['title']}) — {', '.join(m['authors'])}, {m['venue']}",
                "one_line": i["one_line"],
                "sections": sections,
                "blocks": self.ask_blocks,
                "global": overview[:20000],
            }
        return out


def render_book(
    book: dict,
    figures: dict[str, str] | None = None,
    *,
    artifact: bool = False,
    profile: str = "",
    source_name: str = "",
    generated: str | None = None,
) -> str:
    """The textbook page for a normalized, validated book."""
    r = _Renderer(book, figures or {}, artifact=artifact, profile=profile, source_name=source_name)
    generated = generated or dt.date.today().isoformat()
    body = (
        r.cover()
        + r.intro()
        + "".join(r.section(si, s) for si, s in enumerate(book["sections"]))
        + r.wrap()
        + r.colophon(generated)
    )
    m = book["meta"]
    book_id = hashlib.sha1((m["title"] + m["doi"] + m["venue"]).encode("utf-8")).hexdigest()[:12]
    page = (
        f'<div class="app" data-mode="ko" data-notes="on" data-font="serif">{r.topbar()}'
        f'<div class="frame">{r.toc()}<main class="book">{body}</main></div></div>'
        f'<script type="application/json" id="book-data">{_script_json(r.data(book_id))}</script>'
    )
    title = e(m["short_title"] or m["title_ko"] or m["title"] or "논문 교과서")
    head = (
        f"<title>{title}</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        f'<link rel="stylesheet" href="{FONTS_CSS}">\n'
        f"<style>{katex_css()}</style>\n<style>{_asset('style.css')}</style>\n"
    )
    if artifact:
        scripts = f'<script src="{KATEX_CDN}"></script>\n<script>{_asset("app.js")}</script>\n'
        return head + page + "\n" + scripts
    katex_js = (ASSETS / "katex" / "katex.min.js").read_text(encoding="utf-8")
    scripts = f"<script>{katex_js}</script>\n<script>{_asset('app.js')}</script>\n"
    return (
        '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{head}</head>\n<body>\n{page}\n{scripts}</body>\n</html>\n"
    )
