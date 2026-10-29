# nonmoon — 논문을 한국어 교과서로

영어(또는 한국어) 물리학 논문 PDF를 넣으면 **교과서처럼 읽히는 한국어 HTML**을 만들어 줍니다. 문장을 하나씩 복사해 번역기에 붙여 넣던 일을 한 번에 끝내고, 번역에 더해 이해를 돕는 해설까지 붙입니다. 중성원자·분광학·광학 논문을 읽는 연구실 학생을 기준으로 만들었습니다.

## 무엇이 나오나

- **빠짐없는 번역**: 원문 문단마다 한국어 번역. 상단에서 `번역` / `대역`(영어와 한국어 나란히) / `원문` 보기를 바꿀 수 있고, 번역 보기에서도 문단마다 `원문` 버튼으로 영어를 펼쳐 볼 수 있습니다.
- **해설 상자**: 필요한 곳에만 붙는 교과서식 설명 — 개념, 수식 풀이, 직관, 실험실 노트, 주의(원문 오류 포함), 연구 맥락, 생각해 보기.
- **수식 풀이**: 모든 식을 원문 번호 그대로 다시 조판하고, 식 아래에 의미·유도 흐름·기호표를 붙입니다.
- **그림 읽기**: 원문 그림을 잘라 넣고 캡션 번역과 "무엇을 봐야 하는지"를 설명합니다. 본문의 "그림 2", "식 (3)"에 마우스를 올리면 미리보기가 뜹니다.
- **들어가기 전에 / 정리와 확인**: 한 줄 요약, 학습 목표, 미리 알아둘 개념, 절별 요지와 핵심 정리, 확인 문제(풀이 포함), 용어집, 더 읽을거리.
- **용어 풍선**: 본문의 전문 용어(점선 밑줄)를 누르면 영어 원어와 정의가 나옵니다.
- **질문하기**: Claude 화면(Artifact)에서 열면 문단·수식·그림마다 `질문` 버튼이 생겨, 그 부분에 대해 바로 물어볼 수 있습니다 (그림은 이미지까지 함께 보냅니다).
- 휴대폰·태블릿, 다크 모드, 글꼴(명조/고딕)과 글자 크기 조절, 인쇄(파일로 열었을 때).

## 사용법 1 — Claude Code에서 (설치·API 키 필요 없음, 추천)

1. 이 저장소를 Claude Code(웹 claude.ai/code 또는 데스크톱 앱)에서 엽니다.
2. 논문 PDF를 첨부하고 `/textbook` 이라고 치거나 "이 논문 교과서로 만들어줘"라고 말합니다.
3. Claude가 논문을 읽고 번역·해설을 쓴 뒤 **비공개 Artifact 링크**를 줍니다. 링크는 PC·휴대폰 어디서나 열립니다.

Claude 구독 사용량만 쓰고 별도 비용은 없습니다. 논문 길이에 따라 10~30분쯤 걸립니다.

## 사용법 2 — 내 컴퓨터에서 명령 한 줄로 (Claude API 키 필요)

```bash
git clone https://github.com/jeondusan-cloud/nonmoon.git
cd nonmoon
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...      # https://console.anthropic.com 에서 발급
nonmoon build 논문.pdf --open
```

몇 분 뒤 `output/<이름>.html`이 만들어지고 브라우저로 열립니다. 이 파일 하나에 그림과 수식 글꼴이 모두 들어 있어 인터넷 없이도 열립니다.

- 비용: 끝날 때 실제 토큰 사용량과 대략의 금액을 보여 줍니다. 6쪽짜리 논문이면 기본 모델(Claude Opus 5.5)로 대략 1~2달러, `--model claude-sonnet-5-5`로는 그 절반 정도로 예상합니다.
- 중간에 끊겨도 다시 실행하면 이미 받은 결과는 그대로 쓰고 이어서 진행합니다 (`work/<이름>/api/`에 저장).
- 긴 문서(학위 논문 등)는 `--pages 1-20`처럼 필요한 쪽만 고르세요.
- Claude가 응답을 거절하면 서버 쪽에서 다른 모델로 자동 재시도하도록(`fallbacks`) 설정해 두었습니다.

### 명령어 정리

| 명령 | 하는 일 |
|---|---|
| `nonmoon build 논문.pdf [--open] [--model ...] [--effort low/medium/high] [--pages 1-8]` | PDF → 교과서 HTML (API 사용) |
| `nonmoon prepare 논문.pdf` | PDF를 쪽 이미지·텍스트로 풀어 작업 폴더 만들기 |
| `nonmoon render work/<이름> [--artifact]` | 작업 폴더의 `book.yaml`/`book.json` → HTML 다시 만들기 (API 안 씀) |
| `nonmoon check work/<이름>` | 형식·수식(KaTeX)·용어 표기 검사 |

## 해설의 눈높이 바꾸기

`nonmoon/prompts/profile.md`(독자 프로필)를 고치면 해설의 깊이와 예시가 바뀝니다. 자기 연구 주제나 아는 것/모르는 것을 적어 두세요. 다른 파일을 쓰려면 `--profile 내프로필.md`. 번역 용어와 해설 규칙은 `nonmoon/prompts/style_guide.md`에 있습니다.

## 주의

- AI가 쓴 번역과 해설입니다. 수식, 수치, 인용은 원문으로 꼭 확인하세요. 원문의 오타나 모호한 부분은 "주의" 상자로 짚도록 했습니다.
- 이 저장소는 공개(public) 저장소입니다. 논문 PDF와 번역 결과물은 저작권 문제가 있을 수 있어 `.gitignore`로 커밋되지 않게 막아 두었습니다 (`*.pdf`, `work/`, `output/`, `papers/`).

## 구조 (개발용)

```
nonmoon/
  cli.py        명령어
  pdfprep.py    PDF → 쪽 이미지·텍스트, 그림 잘라내기 (PyMuPDF)
  llm.py        Claude API 파이프라인 (설계 → 절별 번역·해설 → 그림 위치)
  schema.py     교과서 데이터 형식 (구조화 출력 스키마)
  book.py       book.yaml/json 읽기·정리·검사
  markup.py     본문 마크다운 + 수식 + 용어/그림/식 연결
  render.py     HTML 만들기 (파일용 / Artifact용)
  assets/       화면 CSS·JS, KaTeX
  prompts/      집필 지침, 독자 프로필, 단계별 지시문
.claude/skills/textbook/SKILL.md   Claude Code용 작업 절차
docs/FORMAT.md                     book.yaml 형식 설명
```

테스트: `pip install -e ".[dev]" && pytest`
