import copy
from pathlib import Path

import jsonschema
import pytest

from nonmoon import book as books
from nonmoon import schema

FIXTURE = Path(__file__).parent / "fixtures" / "sample"


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]")


@pytest.mark.parametrize("name", ["PLAN_SCHEMA", "SECTION_SCHEMA", "LOCATE_SCHEMA", "BOOK_SCHEMA"])
def test_schemas_fit_structured_outputs(name):
    """Structured outputs need closed objects, required properties, few unions."""
    s = getattr(schema, name)
    jsonschema.Draft202012Validator.check_schema(s)
    unions = 0
    for path, node in _walk(s):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert set(node.get("required", [])) == set(node.get("properties", {})), path
        if "anyOf" in node or isinstance(node.get("type"), list):
            unions += 1
        for banned in ("minimum", "maximum", "minLength", "maxLength", "oneOf"):
            assert banned not in node, f"{path} uses {banned}"
    assert unions <= 16


def test_load_fixture_and_validate():
    b = books.validate(books.load(FIXTURE))
    assert b["meta"]["short_title"] == "포화 흡수 분광 노트"
    assert [s["id"] for s in b["sections"]] == ["s1", "s2"]
    eq = b["sections"][0]["blocks"][2]
    assert eq["type"] == "equation" and eq["number"] == "1" and eq["latex"].startswith("\\Delta")
    assert b["figures"][0]["bbox"] == [0.1, 0.1, 0.9, 0.45]


def test_sections_directory_is_merged(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "book.yaml").write_text("meta: {title: T, source_language: en}\n", encoding="utf-8")
    (tmp_path / "sections" / "02-b.yaml").write_text("id: s2\ntitle: B\nblocks: []\n", encoding="utf-8")
    (tmp_path / "sections" / "01-a.yaml").write_text(
        "id: s1\ntitle: A\nblocks:\n  - original: Hello\n    translation: 안녕\n", encoding="utf-8"
    )
    b = books.validate(books.load(tmp_path))
    assert [s["id"] for s in b["sections"]] == ["s1", "s2"]
    para = b["sections"][0]["blocks"][0]
    assert para == {"type": "paragraph", "original": "Hello", "translation": "안녕", "notes": []}


def test_normalize_coerces_and_infers():
    b = books.normalize(
        {
            "meta": {"title": "T"},
            "sections": [
                {
                    "blocks": [
                        {"latex": "E=mc^2", "number": 3},
                        {"kind": "lab", "body": "x"},
                        {"type": "figure", "id": "fig1"},
                    ]
                }
            ],
            "figures": [{"id": "fig1", "page": "2", "bbox": "0.1, 0.2, 0.5, 0.6"}],
        }
    )
    blocks = b["sections"][0]["blocks"]
    assert blocks[0]["type"] == "equation" and blocks[0]["number"] == "3"
    assert blocks[1]["type"] == "note" and blocks[1]["kind"] == "lab"
    assert b["figures"][0]["page"] == 2 and b["figures"][0]["bbox"] == [0.1, 0.2, 0.5, 0.6]
    assert b["figures"][0]["label"] == "그림 1"
    assert books.problems(b) == []


def test_problems_are_reported_by_location():
    b = books.load(FIXTURE)
    bad = copy.deepcopy(b)
    bad["sections"][0]["blocks"].append({"type": "figure", "id": "fig9"})
    bad["sections"][1]["blocks"][1]["notes"] = [{"kind": "joke", "title": "", "body": "x"}]
    bad["figures"][0]["bbox"] = [0.5, 0.5, 0.2, 0.9]
    found = "\n".join(books.problems(bad))
    assert "fig9" in found
    assert "sections[1].blocks[1].notes[0]" in found
    assert "figures[0].bbox" in found
    with pytest.raises(books.BookError):
        books.validate(bad)


def test_yaml_syntax_error_is_readable(tmp_path):
    (tmp_path / "book.yaml").write_text("meta:\n  title: A: B: C\n", encoding="utf-8")
    with pytest.raises(books.BookError, match="문법 오류"):
        books.load(tmp_path)
