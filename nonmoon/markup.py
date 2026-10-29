"""A small Markdown dialect for book text, with LaTeX math.

Book text may use: paragraphs separated by blank lines, ``-``/``1.`` lists,
``**bold**``, ``*italic*``, ``` `code` ```, ``[text](https://...)`` links,
inline math ``$...$`` or ``\\(...\\)`` and display math ``$$...$$`` or
``\\[...\\]``. Everything else is escaped, so book text can never inject HTML.

Math is not rendered here: it becomes ``<span class="math-inline|math-display"
data-tex="...">`` and KaTeX renders it in the browser (the TeX stays visible
as a fallback if KaTeX cannot load).

``Linker`` adds two reading aids while rendering: glossary terms become
hoverable (first use per section), and mentions such as "그림 2", "Fig. 3",
"식 (4)" or "Eq. (5)" link to the figure or equation.
"""

from __future__ import annotations

import html
import re

_PH = "\x00"  # placeholder delimiter for extracted math

_MATH_RE = re.compile(
    r"(?<!\\)\$\$(?P<d1>.+?)(?<!\\)\$\$"  # $$ display $$
    r"|\\\[(?P<d2>.+?)\\\]"  # \[ display \]
    r"|\\\((?P<i1>.+?)\\\)"  # \( inline \)
    r"|(?<![\\$])\$(?!\s)(?P<i2>[^$]+?)(?<![\\\s])\$(?!\d)",  # $inline$
    re.S,
)
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_ITALIC_RE = re.compile(r"(?<![\*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\*\w])")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_CITE_RE = re.compile(r"\[(\d+(?:\s*[–\-,]\s*\d+)*)\](?!\()")
_UL_RE = re.compile(r"^\s{0,3}[-*•]\s+")
_OL_RE = re.compile(r"^\s{0,3}(\d+)[.)]\s+")
_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")

# LaTeX commands that a missing backslash-escape in JSON turns into control
# characters: "\frac" -> form feed + "rac", "\theta" -> tab + "heta", ...
_TEX_WORDS = set(
    (
        "alpha approx ast bar beta big bigg bigl bigr bm boldsymbol bot bra braket "
        "frac forall flat "
        "nabla ne neq newline ni nleq ngeq not nu "
        "rangle rho right rightarrow rm rceil rfloor "
        "tau text textbf textit textrm theta times tilde top to tfrac triangle "
        "varepsilon varphi vartheta vec vee vert"
    ).split()
)
_CONTROL_TO_LETTER = {"\x07": "a", "\x08": "b", "\x0c": "f", "\n": "n", "\r": "r", "\t": "t", "\x0b": "v"}
_REPAIR_RE = re.compile("([\x07\x08\x0c\n\r\t\x0b])([A-Za-z]+)")


_MATH_SPAN_RE = re.compile(r"\$\$.+?\$\$|\$[^$]+?\$|\\\(.+?\\\)|\\\[.+?\\\]", re.S)


def repair_tex_escapes(text: str, math_only: bool = True) -> str:
    """Undo JSON escapes that ate the backslash of a LaTeX command.

    With ``math_only`` only text between math delimiters is touched; use
    ``math_only=False`` for fields that hold bare LaTeX.
    """

    def fix(match: re.Match) -> str:
        word = _CONTROL_TO_LETTER[match.group(1)] + match.group(2)
        return "\\" + word if word in _TEX_WORDS else match.group(0)

    if not math_only:
        return _REPAIR_RE.sub(fix, text)
    return _MATH_SPAN_RE.sub(lambda m: _REPAIR_RE.sub(fix, m.group(0)), text)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


class Linker:
    """Glossary terms and figure/equation cross references for one book."""

    def __init__(self, glossary=(), figures=None, equations=None):
        self.terms: list[tuple[str, int]] = []
        en_terms: list[tuple[str, int]] = []
        for index, entry in enumerate(glossary):
            ko = (entry.get("ko") or "").strip()
            en = (entry.get("en") or "").strip()
            if len(ko) >= 2:
                self.terms.append((ko, index))
            if len(en) >= 3:
                en_terms.append((en, index))
        self.terms.sort(key=lambda t: -len(t[0]))
        en_terms.sort(key=lambda t: -len(t[0]))
        self._ko = {t: i for t, i in self.terms}
        self._en = {t.lower(): i for t, i in en_terms}
        self._ko_re = (
            re.compile("|".join(re.escape(html.escape(t, quote=False)) for t, _ in self.terms)) if self.terms else None
        )
        self._en_re = (
            re.compile(
                r"(?<![A-Za-z])(" + "|".join(re.escape(html.escape(t, quote=False)) for t, _ in en_terms) + r")(?![A-Za-z])",
                re.I,
            )
            if en_terms
            else None
        )
        self.figures = figures or {}  # "2" -> "fig-fig2"
        self.equations = equations or {}  # "3" -> "eq-3"
        self.used: dict[bool, set[int]] = {False: set(), True: set()}

    def new_scope(self) -> None:
        """Link each term again from the next section on."""
        self.used = {False: set(), True: set()}

    def _term(self, text: str, index: int, english: bool) -> str:
        if index in self.used[english]:
            return text
        self.used[english].add(index)
        return f'<span class="term" data-g="{index}" tabindex="0">{text}</span>'

    def link_terms(self, text: str, english: bool) -> str:
        if english:
            if not self._en_re:
                return text
            return self._en_re.sub(
                lambda m: self._term(m.group(0), self._en[html.unescape(m.group(0)).lower()], True), text
            )
        if not self._ko_re:
            return text
        return self._ko_re.sub(lambda m: self._term(m.group(0), self._ko[html.unescape(m.group(0))], False), text)

    def link_refs(self, text: str) -> str:
        if self.figures:
            text = re.sub(
                r"(그림|Figs?\.|FIGS?\.|Figures?)\s?(\d+)(?:\s?\(([a-z])\))?",
                lambda m: self._ref(
                    m, self.figures.get(m.group(2) + (m.group(3) or "")) or self.figures.get(m.group(2)), "fig"
                ),
                text,
            )
        if self.equations:
            text = re.sub(
                r"(식|Eqs?\.|Equations?)\s?\((\d+)\)|(식|Eq\.)\s?(\d+)(?![\d.])",
                lambda m: self._ref(m, self.equations.get(m.group(2) or m.group(4)), "eq"),
                text,
            )
        return text

    @staticmethod
    def _ref(match: re.Match, target: str | None, kind: str) -> str:
        if not target:
            return match.group(0)
        return f'<a class="xref" data-ref="{kind}" href="#{target}">{match.group(0)}</a>'


def protect_math(text: str) -> tuple[str, list[tuple[str, bool]]]:
    found: list[tuple[str, bool]] = []

    def take(match: re.Match) -> str:
        display = match.group("d1") is not None or match.group("d2") is not None
        tex = next(g for g in (match.group("d1"), match.group("d2"), match.group("i1"), match.group("i2")) if g is not None)
        found.append((tex.strip(), display))
        return f"{_PH}{len(found) - 1}{_PH}"

    text = _MATH_RE.sub(take, text)
    return text, found


def _restore_math(text: str, found: list[tuple[str, bool]]) -> str:
    def put(match: re.Match) -> str:
        tex, display = found[int(match.group(1))]
        cls = "math-display" if display else "math-inline"
        return f'<span class="{cls}" data-tex="{_attr(tex)}">{html.escape(tex)}</span>'

    return re.sub(f"{_PH}(\\d+){_PH}", put, text)


def _inline(text: str, linker: Linker | None, english: bool) -> str:
    """Escape and format one run of text (math already protected)."""
    text = html.escape(text, quote=False).replace("\\$", "$")
    codes: list[str] = []

    def keep_code(match: re.Match) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return f"{_PH}c{len(codes) - 1}{_PH}"

    text = _CODE_RE.sub(keep_code, text)
    text = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _CITE_RE.sub(r'<span class="cite">[\1]</span>', text)
    if linker:
        parts = _TAG_SPLIT_RE.split(text)
        depth_a = 0
        for i, part in enumerate(parts):
            if part.startswith("<"):
                if part.startswith("<a "):
                    depth_a += 1
                elif part == "</a>":
                    depth_a -= 1
                continue
            if depth_a == 0 and part:
                part = linker.link_refs(part)
                # link_refs may add <a> tags; only link terms outside them.
                pieces = _TAG_SPLIT_RE.split(part)
                inside = 0
                for j, piece in enumerate(pieces):
                    if piece.startswith("<a "):
                        inside += 1
                    elif piece == "</a>":
                        inside -= 1
                    elif not piece.startswith("<") and inside == 0:
                        pieces[j] = linker.link_terms(piece, english)
                parts[i] = "".join(pieces)
        text = "".join(parts)
    return re.sub(f"{_PH}c(\\d+){_PH}", lambda m: codes[int(m.group(1))], text)


def _balanced(html_text: str) -> bool:
    """True when every inline tag opened in ``html_text`` is also closed."""
    return all(
        html_text.count(f"<{tag}") == html_text.count(f"</{tag}>") for tag in ("strong", "em", "a", "span", "code")
    )


def render_inline(text: str, linker: Linker | None = None, english: bool = False) -> str:
    """One line of text (titles, list items): no paragraphs or lists."""
    protected, found = protect_math(text or "")
    return _restore_math(_inline(" ".join(protected.split("\n")), linker, english), found)


def render(text: str, linker: Linker | None = None, english: bool = False) -> str:
    """Block text: paragraphs, lists and display math."""
    protected, found = protect_math((text or "").strip())
    if not protected:
        return ""
    out: list[str] = []
    for chunk in re.split(r"\n\s*\n", protected):
        lines = chunk.split("\n")
        paragraph: list[str] = []
        items: list[str] = []
        list_tag = ""

        def flush_paragraph():
            if not paragraph:
                return
            body = _inline(" ".join(s.strip() for s in paragraph), linker, english)
            # Display math is a block of its own: close the paragraph around it,
            # unless it sits inside inline markup such as **...**.
            text: list[str] = []
            for part in re.split(f"({_PH}\\d+{_PH})", body):
                index = re.fullmatch(f"{_PH}(\\d+){_PH}", part)
                if index and found[int(index.group(1))][1] and _balanced("".join(text)):
                    if "".join(text).strip():
                        out.append(f"<p>{''.join(text).strip()}</p>")
                    out.append(f'<div class="math-block">{part}</div>')
                    text = []
                else:
                    text.append(part)
            if "".join(text).strip():
                out.append(f"<p>{''.join(text).strip()}</p>")
            paragraph.clear()

        def flush_list():
            nonlocal list_tag
            if items:
                lis = "".join(f"<li>{_inline(item, linker, english)}</li>" for item in items)
                out.append(f"<{list_tag}>{lis}</{list_tag}>")
                items.clear()
            list_tag = ""

        for line in lines:
            ul, ol = _UL_RE.match(line), _OL_RE.match(line)
            if ul or ol:
                tag = "ul" if ul else "ol"
                flush_paragraph()
                if list_tag and list_tag != tag:
                    flush_list()
                list_tag = tag
                items.append(line[(ul or ol).end():].strip())
            elif items and line.startswith((" ", "\t")) and line.strip():
                items[-1] += " " + line.strip()
            else:
                flush_list()
                if line.strip():
                    paragraph.append(line)
        flush_paragraph()
        flush_list()
    return _restore_math("".join(out), found)


def plain(text: str) -> str:
    """Text with markup removed (for tooltips and prompts). Math stays as $TeX$."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "", flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    return text.strip()
