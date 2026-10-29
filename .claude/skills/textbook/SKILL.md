---
name: textbook
description: 물리학 논문 PDF를 한국어 교과서(빠짐없는 번역 + 해설 + 수식 풀이 + 그림 읽기 + 확인 문제) HTML로 만들어 Artifact로 보여 준다. 사용자가 논문 PDF를 올리고 "교과서로 만들어줘", "번역해줘", "해설해줘", "이 논문 읽기 쉽게" 등을 요청할 때 쓴다. Use when the user uploads a physics paper PDF and wants a Korean textbook-style translation with explanations.
---

# 논문 → 한국어 교과서

API 키 없이 이 세션의 Claude가 직접 번역·해설을 쓰고, `nonmoon` 렌더러로 교과서 HTML을 만든다. 결과는 비공개 Artifact로 게시한다.

## 0. 준비

- `python3 -c "import nonmoon, pymupdf, yaml, jsonschema"`가 실패하면 저장소 루트에서 `pip install -e .`
- 반드시 먼저 읽는다: `nonmoon/prompts/style_guide.md`(집필 지침), `nonmoon/prompts/profile.md`(독자 프로필; 루트에 `profile.md`가 있으면 그것을 우선), `docs/FORMAT.md`(데이터 형식).
- 이 저장소는 공개(public)다. 논문 PDF, `work/`, `output/`은 `.gitignore`에 있으니 커밋하지 않는다.

## 1. PDF 준비

PDF 경로는 사용자가 첨부한 파일(업로드 경로) 또는 `papers/` 안의 파일이다. 이름(slug)은 짧은 영문/한글로 정한다.

```bash
python3 -m nonmoon prepare <pdf> --work work/<slug>          # 긴 문서면 --pages 1-12
```

`work/<slug>/info.json`에서 쪽 수, 텍스트 레이어 유무(`text_layer`), 그림 캡션 후보를 확인한다.

## 2. 꼼꼼히 읽기

- 모든 쪽을 이미지로 본다: `pages/pNNN.png`(전체), 작은 글씨와 수식은 `pages/pNNN-top.png`, `pNNN-bot.png`(두 배 해상도)로 확인한다.
- 텍스트 레이어가 있으면 `text/pNNN.txt`를 참고하되, 수식·그리스 문자는 텍스트가 깨져 있을 수 있으니 반드시 이미지로 확인한다. 스캔본(`text_layer: false`)은 이미지만 보고 옮긴다.
- 구조(절, 그림, 식 번호, 참고문헌)를 먼저 파악한다.

## 3. 쓰기

1. `work/<slug>/book.yaml`: `meta`, `intro`, `figures`, `glossary`, `summary`, `references`. (절은 쓰지 않는다)
2. 절마다 `work/<slug>/sections/NN-<id>.yaml` 하나씩 쓴다. 한 번에 한 절씩, 원문의 모든 문단·수식·표를 순서대로 옮기고 지침대로 해설을 붙인다.
3. 그림 `bbox`: `pages/pNNN-grid.png`(0.1 격자)를 보고 비율 좌표를 잰다. 캡션은 빼고, 축 글자는 넣는다.

YAML 요령: 수식이 든 글은 `|` 블록 문자열, LaTeX 한 줄은 작은따옴표, `:`가 든 제목은 따옴표.

## 4. 검사와 렌더링

```bash
python3 -m nonmoon check work/<slug>       # 오류가 없을 때까지 고친다 (경고도 가능하면 고친다)
python3 -m nonmoon render work/<slug> --artifact -o output/<slug>.html
```

- `work/<slug>/figures/*.png`(잘라낸 그림)를 직접 열어 보고, 잘리거나 남는 부분이 있으면 `bbox`를 고쳐 다시 렌더링한다.
- 내용 검토: 번역 누락이 없는지(원문 문단 수와 블록 수 비교), 수식 번호가 원문과 같은지, 해설의 수치가 정확한지.

## 5. 게시

Artifact 도구로 `output/<slug>.html`을 게시한다.

- `capabilities: {"sample": {"images": true}}` — 문단·수식·그림마다 "질문" 버튼이 생겨, 읽는 사람이 자기 Claude로 바로 물어볼 수 있다.
- `icon: "book"`, `description`: 한 문장 설명 (예: "PRA 77, 032513 편광 분광 논문의 한국어 번역과 해설").
- 사용자에게 링크와 함께 핵심(몇 개 절, 그림, 특이 사항, 원문 오류를 짚은 곳)을 짧게 알린다.

## 원문이 한국어일 때

`meta.source_language: ko`. 번역은 하지 않고 `original`에 원문을 그대로 옮긴 뒤(`translation` 생략) 해설만 단다. 화면에는 번역/대역/원문 전환 버튼이 나오지 않는다.
