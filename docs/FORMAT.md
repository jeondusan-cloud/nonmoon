# 교과서 데이터 형식 (book.yaml)

`nonmoon render`는 작업 폴더의 `book.yaml`(또는 `book.json`)과 `sections/*.yaml`을 읽어 HTML을 만든다. API 파이프라인은 이 형식을 JSON으로 만들고, Claude Code 스킬은 YAML로 직접 쓴다. 정확한 정의는 `nonmoon/schema.py`의 `BOOK_SCHEMA`이고, 짧은 완성 예시는 `tests/fixtures/sample/book.yaml`이다.

```
work/<이름>/
  source.pdf            nonmoon prepare가 만든 원문 사본
  book.yaml             meta, intro, figures, glossary, summary, references
  sections/01-s1.yaml   절 하나씩 (파일 이름 순서대로 합쳐진다)
  sections/02-s2.yaml
```

## YAML로 쓸 때의 요령

- 수식이 들어가는 글은 블록 문자열 `|`로 쓴다. 블록 문자열 안에서는 `\frac`처럼 역슬래시를 그대로 쓰면 된다.
  ```yaml
  translation: |
    자연 선폭은 $\Gamma/2\pi \approx 6$ MHz이다.
  ```
- 한 줄짜리 값에 `:` 이나 `#`, 따옴표가 있으면 따옴표로 감싼다. LaTeX 한 줄은 작은따옴표가 안전하다: `latex: '\Delta I = I_0 k L \Delta n'`.
- 큰따옴표 안에서는 역슬래시를 두 번 써야 한다(`"\\Gamma"`). 헷갈리면 작은따옴표나 `|`를 쓴다.
- 빠진 필드는 빈 값으로 채워지므로, 해당 없는 필드는 쓰지 않아도 된다 (예: `notes`, `symbols`).

## 최상위 (book.yaml)

```yaml
meta:
  title: "원문 제목"
  title_ko: "번역 제목"
  short_title: "탭에 보일 짧은 이름"      # 2~5단어
  authors: [저자1, 저자2]
  venue: "Physical Review A 77, 032513 (2008)"
  year: "2008"
  doi: "10.1103/PhysRevA.77.032513"
  kind: "연구 논문"                      # 실험 매뉴얼, 리뷰 논문 ...
  source_language: en                   # en | ko | other  (ko면 번역 없이 해설만)

intro:
  one_line: "한 줄 요약"
  overview: |                           # 무엇을, 왜, 어떻게, 결과
    ...
  why_it_matters: |
    ...
  learning_goals: ["...", "..."]
  prerequisites:
    - title: "개념 이름"
      body: |
        짧은 강의
  reading_guide: |
    ...

figures:
  - id: fig1                            # 본문에서 {type: figure, id: fig1}로 배치
    label: "그림 1"
    label_original: "FIG. 1"
    page: 1                             # source.pdf의 쪽 번호 (1부터)
    bbox: [0.52, 0.70, 0.92, 0.86]      # 쪽 비율 좌표 [x0, y0, x1, y1], 캡션 제외
    caption_original: "FIG. 1. ..."
    caption_ko: "그림 1. ..."
    explanation: |                      # 그림 읽기
      ...

glossary:
  - en: "optical pumping"
    ko: "광펌핑"                         # 본문 표기와 똑같이 (용어 풍선이 연결됨)
    definition: "..."

summary:
  key_points: ["...", "..."]
  questions:
    - q: "문제"
      a: |
        풀이와 답
  further_reading:
    - ref: "[1] ..."
      why: "왜 읽을 만한지"

references: ["[1] ...", "[2] ..."]
```

## 절 (sections/NN-id.yaml)

```yaml
id: s2
number: "II"
title: "THEORY"
title_ko: "이론"
summary: |
  이 절의 요지 2~4문장
blocks:
  - type: heading
    original: "A. Rate equations"
    ko: "가. 속도 방정식"

  - type: paragraph
    original: |
      원문 문단 (수식은 $...$)
    translation: |
      번역 문단
    notes:                              # 필요할 때만
      - kind: concept                   # concept | math | intuition | lab | caution | context | question
        title: "짧은 제목"
        body: |
          해설

  - type: equation
    number: "3"
    latex: '\Delta I = I_0 k L \Delta n'
    explanation: |
      이 식의 의미와 유도 흐름
    symbols:
      - symbol: '\Delta n'
        meaning: "굴절률 차이 $n_+ - n_-$"

  - type: figure
    id: fig2

  - type: table
    caption_original: "TABLE I. ..."
    caption_ko: "표 I. ..."
    header: ["물리량", "값"]
    rows:
      - ["자연 선폭", "6.07 MHz"]

  - type: note                          # 문단에 속하지 않는 독립 해설
    kind: lab
    title: "실험실에서는"
    body: |
      ...
key_points:
  - "핵심 정리 1"
```

## 검사

```bash
python -m nonmoon check work/<이름>
```

형식 오류, KaTeX가 그리지 못하는 수식, 짝이 안 맞는 `$`, 본문에 없는 용어집 표기, 빈 번역을 알려 준다.
