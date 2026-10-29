import json

import pytest

from fake_api import FakeAPI
from nonmoon import book as books
from nonmoon import llm, pdfprep

PLAN = {
    "meta": {
        "title": "A Short Test Paper",
        "title_ko": "짧은 시험 논문",
        "short_title": "시험 논문",
        "authors": ["T. Tester"],
        "venue": "Test Journal 1, 1 (2026)",
        "year": "2026",
        "doi": "",
        "kind": "연구 논문",
        "source_language": "en",
    },
    "intro": {
        "one_line": "시험용 논문이다.",
        "overview": "개요.",
        "why_it_matters": "중요성.",
        "learning_goals": ["목표"],
        "prerequisites": [{"title": "개념", "body": "설명"}],
        "reading_guide": "안내.",
    },
    "sections": [
        {"id": "s1", "number": "", "title": "Abstract", "title_ko": "초록", "pages": "1",
         "starts_with": "Abstract. We test", "next_starts_with": "I. INTRODUCTION Body text"},
        {"id": "s2", "number": "I", "title": "INTRODUCTION", "title_ko": "서론", "pages": "1",
         "starts_with": "I. INTRODUCTION Body text", "next_starts_with": "II. THEORY More"},
        {"id": "s3", "number": "II", "title": "THEORY", "title_ko": "이론", "pages": "2",
         "starts_with": "II. THEORY More", "next_starts_with": ""},
    ],
    "figures": [
        {"id": "fig1", "label": "그림 1", "label_original": "FIG. 1", "page": 1,
         "caption_original": "FIG. 1. A straight line in a box.", "caption_ko": "그림 1. 상자 속 직선.", "explanation": "직선이다."}
    ],
    "glossary": [{"en": "pipeline", "ko": "파이프라인", "definition": "처리 단계의 연결."}],
    "summary": {"key_points": ["요점"], "questions": [{"q": "질문?", "a": "답."}], "further_reading": []},
    "references": ["[1] Ref."],
}


def section_reply(body):
    text = body["messages"][0]["content"][-1]["text"]
    number = "II" if "id: s3" in text else ("I" if "id: s2" in text else "")
    blocks = [
        # A JSON-escaping slip: "\frac" sent as form feed + "rac".
        {"type": "paragraph", "original": f"Text of {number or 'abstract'} with $\\frac{{a}}{{b}}$.",
         "translation": "번역 $\x0crac{a}{b}$.", "notes": []},
    ]
    if number == "I":
        blocks.append({"type": "figure", "id": "fig1"})
        blocks.append({"type": "figure", "id": "fig7"})  # unknown: must be dropped
        blocks.append({"type": "equation", "number": "1", "latex": "\x0crac{1}{2}mv^2", "explanation": "운동 에너지.",
                       "symbols": [{"symbol": "m", "meaning": "질량"}], "notes": []})
    return {"summary": "요지.", "blocks": blocks, "key_points": ["핵심"]}


def replies(keys, body):
    if "meta" in keys:
        return json.dumps(PLAN, ensure_ascii=False), "end_turn"
    if keys == ("figures",):
        return json.dumps({"figures": [{"id": "fig1", "page": 1, "bbox": [0.9, 0.46, 0.15, 0.17]}]}), "end_turn"
    return json.dumps(section_reply(body), ensure_ascii=False), "end_turn"


@pytest.fixture
def work(paper, tmp_path):
    w = tmp_path / "work"
    pdfprep.prepare(paper, w)
    return w


def test_full_build_through_the_sdk(work):
    api = FakeAPI(replies)
    pipeline = llm.Pipeline(work, profile="독자 프로필 내용", client=api.client(), log=lambda *_: None)
    book = books.validate(books.normalize(pipeline.run(workers=2)))

    assert len(api.requests) == 5  # plan + 3 sections + locate
    plan_req, first_section = api.requests[0]["body"], api.requests[1]["body"]
    assert plan_req["model"] == "claude-opus-5-5"
    assert plan_req["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in api.requests[0]["headers"]["anthropic-beta"]
    assert plan_req["output_config"]["effort"] == "medium"
    assert "독자 프로필 내용" in plan_req["system"] and "자주 쓰는 용어" in plan_req["system"]
    doc = plan_req["messages"][0]["content"][0]
    assert doc["type"] == "document" and doc["cache_control"] == {"type": "ephemeral"}
    assert first_section["messages"][0]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert "id: s1" in first_section["messages"][0]["content"][2]["text"]
    locate = api.requests[-1]["body"]["messages"][0]["content"]
    assert any(c["type"] == "image" for c in locate)
    assert "thinking" not in plan_req and "temperature" not in plan_req

    intro = book["sections"][1]
    assert [b["type"] for b in intro["blocks"]] == ["paragraph", "figure", "equation"]
    assert intro["blocks"][0]["translation"] == "번역 $\\frac{a}{b}$."
    assert intro["blocks"][2]["latex"] == "\\frac{1}{2}mv^2"
    assert book["figures"][0]["bbox"] == [0.15, 0.17, 0.9, 0.46]
    assert pipeline.usage.requests == 5 and pipeline.usage.cost("claude-opus-5-5") > 0

    # A second run reuses every saved response.
    again = FakeAPI(replies)
    llm.Pipeline(work, client=again.client(), log=lambda *_: None).run()
    assert again.requests == []


def test_refusal_and_truncation_stop_the_build(work):
    refuse = FakeAPI(lambda keys, body: ("{}", "refusal"))
    with pytest.raises(llm.PipelineError, match="답하지 않았습니다"):
        llm.Pipeline(work, client=refuse.client(), log=lambda *_: None).run()
    cut = FakeAPI(lambda keys, body: ("{", "max_tokens"))
    with pytest.raises(llm.PipelineError, match="잘렸습니다"):
        llm.Pipeline(work, client=cut.client(), log=lambda *_: None, force=True).run()


def test_models_without_fallback_send_no_beta(work):
    api = FakeAPI(replies)
    llm.Pipeline(work, model="claude-haiku-5-5", client=api.client(), log=lambda *_: None).plan()
    body = api.requests[0]["body"]
    assert "fallbacks" not in body
    assert "anthropic-beta" not in api.requests[0]["headers"]
