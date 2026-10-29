"""Load, normalize and validate books.

A book lives in a work directory::

    work/<slug>/
      source.pdf          the paper (written by ``nonmoon prepare``)
      book.yaml           meta, intro, figures, glossary, summary, references
      sections/*.yaml     one file per section, merged in file-name order

``book.json`` works in place of ``book.yaml`` (the API pipeline writes JSON),
and ``book.yaml`` may also hold the sections inline under ``sections:``.

Hand-written YAML is forgiving: ``normalize`` fills in missing fields with
empty values and turns numbers into strings where the format wants strings,
so only the parts that matter have to be written out. ``validate`` then
checks the result strictly against ``schema.BOOK_SCHEMA``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import yaml

from . import schema

BOOK_FILES = ("book.yaml", "book.yml", "book.json")


class BookError(Exception):
    """A book that cannot be loaded or does not match the format."""


# --- loading -----------------------------------------------------------------


def _read_data(path: Path):
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise BookError(f"{path}: 파일을 읽을 수 없습니다 (문법 오류)\n{exc}") from exc


def find_book_file(workdir: Path) -> Path | None:
    for name in BOOK_FILES:
        if (workdir / name).is_file():
            return workdir / name
    return None


def load(path: str | Path) -> dict:
    """Load a book from a work directory or a single book file, normalized."""
    path = Path(path)
    if path.is_dir():
        book_file = find_book_file(path)
        if book_file is None:
            raise BookError(f"{path}: book.yaml 또는 book.json이 없습니다.")
        workdir = path
    else:
        book_file, workdir = path, path.parent
    data = _read_data(book_file)
    if not isinstance(data, dict):
        raise BookError(f"{book_file}: 최상위가 매핑(키: 값)이어야 합니다.")
    sections = list(data.get("sections") or [])
    section_dir = workdir / "sections"
    if section_dir.is_dir():
        files = sorted(
            p for p in section_dir.iterdir() if p.suffix in (".yaml", ".yml", ".json") and not p.name.startswith(".")
        )
        for file in files:
            part = _read_data(file)
            if isinstance(part, list):
                sections.extend(part)
            elif isinstance(part, dict):
                sections.append(part)
            else:
                raise BookError(f"{file}: 절 하나(매핑) 또는 절 목록이어야 합니다.")
    data["sections"] = sections
    return normalize(data)


# --- normalizing -------------------------------------------------------------


def _s(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _note(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {"body": _s(raw)}
    kind = _s(raw.get("kind") or "concept").strip().lower()
    return {"kind": kind, "title": _s(raw.get("title")), "body": _s(raw.get("body"))}


def _guess_block_type(raw: dict) -> str:
    if "latex" in raw:
        return "equation"
    if "rows" in raw or "header" in raw:
        return "table"
    if set(raw) <= {"id", "type"} and _s(raw.get("id")).startswith("fig"):
        return "figure"
    if "kind" in raw and "body" in raw:
        return "note"
    if "ko" in raw and "original" in raw and "translation" not in raw:
        return "heading"
    return "paragraph"


def _block(raw) -> dict:
    if isinstance(raw, str):
        raw = {"type": "paragraph", "original": raw}
    if not isinstance(raw, dict):
        raise BookError(f"블록은 매핑이어야 합니다: {raw!r}")
    kind = _s(raw.get("type")).strip().lower() or _guess_block_type(raw)
    notes = [_note(n) for n in _list(raw.get("notes"))]
    if kind == "paragraph":
        return {
            "type": kind,
            "original": _s(raw.get("original")),
            "translation": _s(raw.get("translation")),
            "notes": notes,
        }
    if kind == "equation":
        return {
            "type": kind,
            "number": _s(raw.get("number")),
            "latex": _s(raw.get("latex")).strip(),
            "explanation": _s(raw.get("explanation")),
            "symbols": [
                {"symbol": _s(s.get("symbol")), "meaning": _s(s.get("meaning"))}
                for s in _list(raw.get("symbols"))
                if isinstance(s, dict)
            ],
            "notes": notes,
        }
    if kind == "figure":
        return {"type": kind, "id": _s(raw.get("id"))}
    if kind == "table":
        return {
            "type": kind,
            "caption_original": _s(raw.get("caption_original")),
            "caption_ko": _s(raw.get("caption_ko")),
            "header": [_s(h) for h in _list(raw.get("header"))],
            "rows": [[_s(c) for c in _list(row)] for row in _list(raw.get("rows"))],
            "notes": notes,
        }
    if kind == "note":
        note = _note(raw)
        return {"type": kind, **note}
    if kind == "heading":
        return {"type": kind, "original": _s(raw.get("original")), "ko": _s(raw.get("ko"))}
    # Unknown types are kept so that validation reports them by position.
    return {**raw, "type": kind}


def _section(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise BookError(f"sections[{index}]: 절은 매핑이어야 합니다.")
    return {
        "id": _s(raw.get("id")) or f"s{index + 1}",
        "number": _s(raw.get("number")),
        "title": _s(raw.get("title")),
        "title_ko": _s(raw.get("title_ko")),
        "summary": _s(raw.get("summary")),
        "blocks": [_block(b) for b in _list(raw.get("blocks"))],
        "key_points": [_s(k) for k in _list(raw.get("key_points"))],
    }


def _figure(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise BookError(f"figures[{index}]: 그림 정보는 매핑이어야 합니다.")
    fig_id = _s(raw.get("id")) or f"fig{index + 1}"
    number = re.sub(r"\D", "", fig_id) or str(index + 1)
    try:
        page = int(raw.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    bbox = raw.get("bbox")
    if isinstance(bbox, str):
        bbox = [float(x) for x in re.split(r"[,\s]+", bbox.strip()) if x]
    return {
        "id": fig_id,
        "label": _s(raw.get("label")) or f"그림 {number}",
        "label_original": _s(raw.get("label_original")),
        "page": page,
        "caption_original": _s(raw.get("caption_original")),
        "caption_ko": _s(raw.get("caption_ko")),
        "explanation": _s(raw.get("explanation")),
        "bbox": [float(x) for x in _list(bbox)],
    }


def normalize(data: dict) -> dict:
    meta = data.get("meta") or {}
    intro = data.get("intro") or {}
    summary = data.get("summary") or {}
    lang = _s(meta.get("source_language") or "en").strip().lower()
    return {
        "version": int(data.get("version") or schema.BOOK_VERSION),
        "meta": {
            "title": _s(meta.get("title")),
            "title_ko": _s(meta.get("title_ko")),
            "short_title": _s(meta.get("short_title")),
            "authors": [_s(a) for a in _list(meta.get("authors"))],
            "venue": _s(meta.get("venue")),
            "year": _s(meta.get("year")),
            "doi": _s(meta.get("doi")),
            "kind": _s(meta.get("kind")),
            "source_language": lang,
        },
        "intro": {
            "one_line": _s(intro.get("one_line")),
            "overview": _s(intro.get("overview")),
            "why_it_matters": _s(intro.get("why_it_matters")),
            "learning_goals": [_s(g) for g in _list(intro.get("learning_goals"))],
            "prerequisites": [
                {"title": _s(p.get("title")), "body": _s(p.get("body"))}
                for p in _list(intro.get("prerequisites"))
                if isinstance(p, dict)
            ],
            "reading_guide": _s(intro.get("reading_guide")),
        },
        "sections": [_section(s, i) for i, s in enumerate(_list(data.get("sections")))],
        "figures": [_figure(f, i) for i, f in enumerate(_list(data.get("figures")))],
        "glossary": [
            {"en": _s(g.get("en")), "ko": _s(g.get("ko")), "definition": _s(g.get("definition"))}
            for g in _list(data.get("glossary"))
            if isinstance(g, dict)
        ],
        "summary": {
            "key_points": [_s(k) for k in _list(summary.get("key_points"))],
            "questions": [
                {"q": _s(q.get("q")), "a": _s(q.get("a"))} for q in _list(summary.get("questions")) if isinstance(q, dict)
            ],
            "further_reading": [
                {"ref": _s(r.get("ref")), "why": _s(r.get("why"))}
                for r in _list(summary.get("further_reading"))
                if isinstance(r, dict)
            ],
        },
        "references": [_s(r) for r in _list(data.get("references"))],
    }


# --- validating --------------------------------------------------------------


def _where(path) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(최상위)"


def problems(book: dict) -> list[str]:
    """Everything wrong with a normalized book, as readable messages."""
    found: list[str] = []
    validator = jsonschema.Draft202012Validator(schema.BOOK_SCHEMA)
    for error in sorted(validator.iter_errors(book), key=lambda e: list(e.absolute_path)):
        message = error.message
        if error.validator == "anyOf" and isinstance(error.instance, dict):
            kind = error.instance.get("type")
            message = f"알 수 없는 블록이거나 필드가 잘못됨 (type={kind!r})"
        found.append(f"{_where(error.absolute_path)}: {message}")

    ids = [s["id"] for s in book["sections"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        found.append(f"sections: 절 id '{dup}'가 중복됩니다.")
    figure_ids = {f["id"] for f in book["figures"]}
    for si, section in enumerate(book["sections"]):
        for bi, block in enumerate(section["blocks"]):
            where = f"sections[{si}].blocks[{bi}]"
            if block.get("type") == "figure" and block.get("id") not in figure_ids:
                found.append(f"{where}: figures 목록에 없는 그림 id '{block.get('id')}'")
            if block.get("type") == "equation" and not block.get("latex"):
                found.append(f"{where}: 수식(latex)이 비어 있습니다.")
            if block.get("type") == "paragraph" and not (block.get("original") or block.get("translation")):
                found.append(f"{where}: 문단 내용이 비어 있습니다.")
            for ni, note in enumerate(block.get("notes") or []):
                if note.get("kind") not in schema.NOTE_KINDS:
                    found.append(f"{where}.notes[{ni}]: kind는 {', '.join(schema.NOTE_KINDS)} 중 하나")
    for fi, fig in enumerate(book["figures"]):
        bbox = fig["bbox"]
        if bbox and (len(bbox) != 4 or not (0 <= min(bbox) and max(bbox) <= 1) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
            found.append(f"figures[{fi}].bbox: [x0, y0, x1, y1] (0~1, x0<x1, y0<y1) 형식이어야 합니다: {bbox}")
    if book["meta"]["source_language"] not in ("en", "ko", "other"):
        found.append("meta.source_language: en, ko, other 중 하나")
    return found


def validate(book: dict) -> dict:
    found = problems(book)
    if found:
        listing = "\n".join(f"  - {p}" for p in found[:40])
        more = f"\n  ... 외 {len(found) - 40}개" if len(found) > 40 else ""
        raise BookError(f"교과서 형식 오류 {len(found)}개:\n{listing}{more}")
    return book


# --- helpers used by the renderer and the pipeline -----------------------------


def translated(book: dict) -> bool:
    """Whether the book carries translations (False for Korean papers)."""
    return book["meta"]["source_language"] != "ko"


def iter_blocks(book: dict):
    for section in book["sections"]:
        for block in section["blocks"]:
            yield section, block


def write_json(book: dict, path: Path) -> None:
    path.write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
