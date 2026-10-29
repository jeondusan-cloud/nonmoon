"""The book format.

A *book* is the translated + annotated paper as plain data. Two producers
write it and one consumer reads it:

* the API pipeline (``nonmoon build``) gets it from Claude with structured
  outputs, using ``PLAN_SCHEMA``, ``SECTION_SCHEMA`` and ``LOCATE_SCHEMA``;
* a Claude Code session (the ``textbook`` skill) writes it by hand as YAML;
* the renderer turns it into HTML after ``book.validate`` checks it against
  ``BOOK_SCHEMA``.

Structured outputs accept only a subset of JSON Schema: every object needs
``additionalProperties: false``, no recursion, few optional properties and
few unions. So every property is required here (empty string / empty list
when not applicable) and the only union is the block type.
"""

from __future__ import annotations

import copy

NOTE_KINDS = ["concept", "math", "intuition", "lab", "caution", "context", "question"]

NOTE_KIND_LABELS = {
    "concept": "개념",
    "math": "수식 풀이",
    "intuition": "직관",
    "lab": "실험실 노트",
    "caution": "주의",
    "context": "연구 맥락",
    "question": "생각해 보기",
}

MD = "마크다운(굵게 **, 목록 -, 문단은 빈 줄로 구분)과 LaTeX 수식($...$, $$...$$)을 쓸 수 있다. HTML 금지."


def _obj(props: dict, description: str | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _arr(items: dict, description: str | None = None) -> dict:
    schema = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    return schema


def _const(value: str) -> dict:
    return {"type": "string", "const": value}


NOTE = _obj(
    {
        "kind": {
            "type": "string",
            "enum": NOTE_KINDS,
            "description": (
                "concept=배경 개념, math=수식 풀이/유도, intuition=물리적 직관·비유, "
                "lab=실험실 실무(장비·정렬·수치), caution=흔한 오해·원문 오류, "
                "context=연구사·다른 연구와의 관계, question=독자에게 던지는 질문"
            ),
        },
        "title": _str("해설 상자의 짧은 제목 (한국어, 20자 안팎)"),
        "body": _str("해설 본문 (한국어). " + MD),
    }
)

NOTES = _arr({"$ref": "#/$defs/note"}, "이 블록에 붙는 해설. 이해에 꼭 필요할 때만, 없으면 빈 배열.")

PARAGRAPH = _obj(
    {
        "type": _const("paragraph"),
        "original": _str("원문 문단 그대로(정리된 텍스트, 수식은 LaTeX $...$). 원문이 한국어면 한국어 원문."),
        "translation": _str("문단의 한국어 번역(요약 금지, 빠짐없이). 원문이 한국어면 빈 문자열. " + MD),
        "notes": NOTES,
    },
    "본문 문단 하나",
)

SYMBOL = _obj(
    {
        "symbol": _str("기호 (LaTeX, $ 없이) 예: \\Gamma"),
        "meaning": _str("기호의 뜻과 단위 (한국어). " + MD),
    }
)

EQUATION = _obj(
    {
        "type": _const("equation"),
        "number": _str("원문의 식 번호, 예: \"3\". 번호 없는 식이면 빈 문자열."),
        "latex": _str("디스플레이 수식 LaTeX ($$ 없이). 여러 줄이면 \\begin{aligned}...\\end{aligned}."),
        "explanation": _str("이 식이 말하는 것, 물리적 의미, 근사 조건, 유도 흐름 (한국어). 사소한 식이면 짧게. " + MD),
        "symbols": _arr(SYMBOL, "처음 등장하거나 헷갈리기 쉬운 기호만. 없으면 빈 배열."),
        "notes": NOTES,
    },
    "번호가 붙거나 따로 떨어진 디스플레이 수식",
)

FIGURE_REF = _obj(
    {
        "type": _const("figure"),
        "id": _str("figures 목록의 그림 id, 예: fig1. 그림을 처음 언급하는 문단 바로 뒤에 둔다."),
    },
    "그림을 본문 흐름 속 이 위치에 배치",
)

TABLE = _obj(
    {
        "type": _const("table"),
        "caption_original": _str("원문 표 제목"),
        "caption_ko": _str("표 제목 번역 (원문이 한국어면 빈 문자열)"),
        "header": _arr({"type": "string"}, "열 제목 (한국어로 옮김)"),
        "rows": _arr(_arr({"type": "string"}), "행들. 각 칸은 문자열, 수식은 $...$"),
        "notes": NOTES,
    },
    "표",
)

NOTE_BLOCK = _obj(
    {
        "type": _const("note"),
        "kind": NOTE["properties"]["kind"],
        "title": NOTE["properties"]["title"],
        "body": NOTE["properties"]["body"],
    },
    "특정 문단에 속하지 않는 독립 해설 상자 (예: 절 중간의 개념 정리)",
)

HEADING = _obj(
    {
        "type": _const("heading"),
        "original": _str("원문 소제목 (예: \"A. Rate equations\")"),
        "ko": _str("소제목 번역 (원문이 한국어면 빈 문자열)"),
    },
    "절 안의 소제목",
)

BLOCK = {"anyOf": [PARAGRAPH, EQUATION, FIGURE_REF, TABLE, NOTE_BLOCK, HEADING]}

SECTION_BODY = {
    "summary": _str("이 절의 요지 2~4문장 (한국어). " + MD),
    "blocks": _arr({"$ref": "#/$defs/block"}, "절의 내용을 원문 순서대로. 원문의 모든 문단과 수식을 빠짐없이."),
    "key_points": _arr({"type": "string"}, "이 절의 핵심 정리 2~5개 (한국어 한 문장씩, $수식$ 가능)"),
}

SECTION_HEAD = {
    "id": _str("절 id: s1, s2, ... 순서대로"),
    "number": _str("원문의 절 번호 (예: \"II\", \"3\", \"3.2\"). 없으면 빈 문자열."),
    "title": _str("원문 절 제목 (예: \"THEORY\", \"Abstract\")"),
    "title_ko": _str("절 제목 번역 (예: \"이론\", \"초록\"). 원문이 한국어면 원문 제목."),
}

META = _obj(
    {
        "title": _str("원문 제목"),
        "title_ko": _str("제목 번역 (원문이 한국어면 원문 제목)"),
        "short_title": _str("브라우저 탭에 쓸 짧은 한국어 이름, 2~5단어 (예: \"루비듐 편광 분광\")"),
        "authors": _arr({"type": "string"}, "저자 이름 (원문 표기)"),
        "venue": _str("학술지·권·쪽·연도 (예: \"Physical Review A 77, 032513 (2008)\"). 모르면 빈 문자열."),
        "year": _str("출판 연도, 모르면 빈 문자열"),
        "doi": _str("DOI (예: \"10.1103/PhysRevA.77.032513\"), 없으면 빈 문자열"),
        "kind": _str("문서 종류 (예: \"연구 논문\", \"실험 매뉴얼\", \"리뷰 논문\", \"학위 논문\")"),
        "source_language": {
            "type": "string",
            "enum": ["en", "ko", "other"],
            "description": "원문 언어. ko면 번역 없이 해설만 단다.",
        },
    }
)

INTRO = _obj(
    {
        "one_line": _str("논문 전체를 한 문장으로 (한국어)"),
        "overview": _str("무엇을, 왜, 어떻게, 결과는 무엇인지 2~3문단 (한국어). " + MD),
        "why_it_matters": _str("이 논문이 중요한 이유와 독자의 연구(중성원자 실험)와의 연결 (한국어). " + MD),
        "learning_goals": _arr({"type": "string"}, "다 읽고 나면 할 수 있어야 하는 것 3~6개"),
        "prerequisites": _arr(
            _obj({"title": _str("개념 이름"), "body": _str("미리 알아야 할 개념의 짧은 강의 (한국어). " + MD)}),
            "읽기 전에 알아야 할 배경 개념 2~6개",
        ),
        "reading_guide": _str("어떤 순서·관점으로 읽으면 좋은지, 어려운 부분은 어디인지 (한국어). " + MD),
    }
)

FIGURE_INFO = {
    "id": _str("그림 id: fig1, fig2, ... (원문 번호를 따름)"),
    "label": _str("한국어 그림 이름 (예: \"그림 1\")"),
    "label_original": _str("원문 그림 이름 (예: \"FIG. 1\", \"Figure 2\", \"그림 3\")"),
    "page": {"type": "integer", "description": "그림이 있는 PDF 쪽 번호 (1부터)"},
    "caption_original": _str("원문 캡션 그대로"),
    "caption_ko": _str("캡션 번역 (원문이 한국어면 빈 문자열). " + MD),
    "explanation": _str("그림 읽는 법: 축과 기호, 무엇을 봐야 하는지, 결론 (한국어). " + MD),
}

BBOX = _arr(
    {"type": "number"},
    "그림 영역 [x0, y0, x1, y1]. 쪽 왼쪽 위가 (0,0), 오른쪽 아래가 (1,1)인 비율 좌표. 캡션은 빼고 그림만.",
)

GLOSSARY = _arr(
    _obj(
        {
            "en": _str("영어 용어"),
            "ko": _str("본문에서 쓴 한국어 용어 (본문 표기와 정확히 같게)"),
            "definition": _str("한두 문장 정의 (한국어). " + MD),
        }
    ),
    "용어집: 이 논문을 읽는 데 중요한 전문 용어 10~30개. 본문 번역에서 이 한국어 용어를 일관되게 쓴다.",
)

SUMMARY = _obj(
    {
        "key_points": _arr({"type": "string"}, "논문 전체의 핵심 정리 4~8개"),
        "questions": _arr(
            _obj({"q": _str("확인 문제 (한국어). " + MD), "a": _str("모범 답안과 풀이 (한국어). " + MD)}),
            "이해를 확인하는 문제 3~6개 (계산 문제 포함 권장)",
        ),
        "further_reading": _arr(
            _obj({"ref": _str("참고문헌 (원문 표기 또는 [번호])"), "why": _str("왜 읽을 만한지 (한국어)")}),
            "다음에 읽으면 좋은 문헌 2~5개 (논문의 참고문헌 중심)",
        ),
    }
)

REFERENCES = _arr({"type": "string"}, "원문 참고문헌 목록 그대로 (번호 포함). 없으면 빈 배열.")

DEFS = {"note": NOTE, "block": BLOCK}

# --- API pass 1: overall plan (everything except section bodies and figure boxes)
PLAN_SCHEMA = {
    **_obj(
        {
            "meta": META,
            "intro": INTRO,
            "sections": _arr(
                _obj(
                    {
                        **SECTION_HEAD,
                        "pages": _str("이 절이 걸친 PDF 쪽 범위 (예: \"2-3\")"),
                        "starts_with": _str("이 절 첫 문단의 첫 8~12단어 (원문 그대로)"),
                        "next_starts_with": _str("다음 절 첫 문단의 첫 8~12단어 (원문 그대로). 마지막 절이면 빈 문자열."),
                    }
                ),
                "본문을 나누는 절 목록. 초록(Abstract)도 하나의 절. 참고문헌 목록은 절로 넣지 않는다. "
                "한 절이 원문 2.5쪽을 넘으면 소절 단위로 나눈다.",
            ),
            "figures": _arr(_obj(FIGURE_INFO), "원문의 모든 그림 (표 제외)"),
            "glossary": GLOSSARY,
            "summary": SUMMARY,
            "references": REFERENCES,
        }
    ),
}

# --- API pass 2: one section body
SECTION_SCHEMA = {"$defs": copy.deepcopy(DEFS), **_obj(SECTION_BODY)}

# --- API pass 3: figure boxes, measured on grid-overlay page images
LOCATE_SCHEMA = _obj(
    {
        "figures": _arr(
            _obj({"id": _str("그림 id"), "page": {"type": "integer"}, "bbox": BBOX}),
            "요청받은 그림 각각의 위치",
        )
    }
)

# --- The whole book, as the renderer reads it
BOOK_SCHEMA = {
    "$defs": copy.deepcopy(DEFS),
    **_obj(
        {
            "version": {"type": "integer"},
            "meta": META,
            "intro": INTRO,
            "sections": _arr(_obj({**SECTION_HEAD, **SECTION_BODY})),
            "figures": _arr(_obj({**FIGURE_INFO, "bbox": BBOX})),
            "glossary": GLOSSARY,
            "summary": SUMMARY,
            "references": REFERENCES,
        }
    ),
}

BOOK_VERSION = 1
