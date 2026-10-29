"""The Claude API pipeline: PDF -> book.

Three kinds of request, all with structured outputs:

1. plan     - the PDF in, the whole book except section bodies out
2. section  - one per section, in parallel; the PDF and the plan are cached
3. locate   - grid-overlay images of the figure pages in, figure boxes out

Every response is kept under ``<work>/api/``; a rerun reuses what is there,
so an interrupted build resumes without paying again.
"""

from __future__ import annotations

import base64
import concurrent.futures as cf
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from . import schema
from .markup import repair_tex_escapes

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 64000
MAX_PDF_BYTES = 20 * 1024 * 1024
PROMPTS = Path(__file__).parent / "prompts"

# USD per million tokens: input, output, 5-minute cache write, cache read.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25),
}
# Models that take the server-side refusal fallback in its "default" form.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class PipelineError(Exception):
    """A build step that cannot continue; the message is for the user."""


NO_CREDENTIALS = (
    "Claude API 인증 정보를 찾지 못했습니다.\n"
    "  https://console.anthropic.com 에서 API 키를 만든 뒤\n"
    "  export ANTHROPIC_API_KEY=sk-ant-...   (Windows PowerShell: $env:ANTHROPIC_API_KEY=\"sk-ant-...\")\n"
    "API 키 없이 쓰려면 Claude Code에서 /textbook 스킬을 쓰세요 (README 참고)."
)


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def system_prompt(profile: str) -> str:
    return (
        "당신은 물리학 논문을 한국어 교과서로 옮기는 편집자이자 튜터다. 아래 지침과 독자 프로필을 따른다.\n\n"
        + prompt("style_guide.md")
        + "\n\n---\n\n"
        + profile.strip()
        + "\n"
    )


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, usage) -> None:
        with self.lock:
            self.requests += 1
            self.input += usage.input_tokens or 0
            self.output += usage.output_tokens or 0
            self.cache_write += usage.cache_creation_input_tokens or 0
            self.cache_read += usage.cache_read_input_tokens or 0

    def cost(self, model: str) -> float | None:
        price = PRICES.get(model)
        if not price:
            return None
        p_in, p_out, p_write, p_read = price
        return (self.input * p_in + self.output * p_out + self.cache_write * p_write + self.cache_read * p_read) / 1e6

    def describe(self, model: str) -> str:
        tokens = (
            f"입력 {self.input + self.cache_write + self.cache_read:,} 토큰"
            f"(캐시 읽기 {self.cache_read:,}) · 출력 {self.output:,} 토큰 · 요청 {self.requests}회"
        )
        cost = self.cost(model)
        return tokens + (f" · 약 ${cost:.2f}" if cost is not None else "")


def _repair(value, bare_tex: bool = False):
    """Fix LaTeX backslashes that JSON escaping turned into control characters."""
    if isinstance(value, str):
        return repair_tex_escapes(value, math_only=not bare_tex)
    if isinstance(value, list):
        return [_repair(v, bare_tex) for v in value]
    if isinstance(value, dict):
        return {k: _repair(v, bare_tex or k in ("latex", "symbol")) for k, v in value.items()}
    return value


class Pipeline:
    def __init__(
        self,
        workdir: Path,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        profile: str = "",
        force: bool = False,
        log=print,
        client: anthropic.Anthropic | None = None,
    ):
        self.workdir = Path(workdir)
        self.api_dir = self.workdir / "api"
        self.model = model
        self.effort = effort
        self.force = force
        self.log = log
        self.system = system_prompt(profile)
        self.usage = Usage()
        try:
            self.client = client or anthropic.Anthropic(max_retries=4)
        except anthropic.AnthropicError as exc:
            raise PipelineError(NO_CREDENTIALS) from exc
        pdf = (self.workdir / "source.pdf").read_bytes()
        if len(pdf) > MAX_PDF_BYTES:
            raise PipelineError(
                f"PDF가 너무 큽니다({len(pdf) / 1e6:.1f} MB). --pages 로 필요한 쪽만 골라 주세요."
            )
        self.document = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf).decode()},
            "cache_control": {"type": "ephemeral"},
        }

    # --- one request ---------------------------------------------------------

    def _call(self, content: list, out_schema: dict, label: str, effort: str | None = None) -> dict:
        params = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": self.system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "effort": effort or self.effort,
                "format": {"type": "json_schema", "schema": out_schema},
            },
        }
        if self.model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        try:
            with self.client.beta.messages.stream(**params) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise PipelineError("API 키가 올바르지 않습니다.\n" + NO_CREDENTIALS) from exc
        except anthropic.PermissionDeniedError as exc:
            raise PipelineError(f"이 API 키로는 {self.model} 모델을 쓸 수 없습니다: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise PipelineError(f"모델 '{self.model}'을 찾을 수 없습니다: {exc.message}") from exc
        except anthropic.BadRequestError as exc:
            raise PipelineError(f"{label}: 요청이 거부되었습니다: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise PipelineError(f"{label}: 요청 한도를 넘었습니다. 잠시 뒤 다시 실행하면 이어서 진행합니다.") from exc
        except anthropic.APIStatusError as exc:
            raise PipelineError(f"{label}: API 오류({exc.status_code}). 다시 실행하면 이어서 진행합니다.") from exc
        except anthropic.APIConnectionError as exc:
            raise PipelineError(f"{label}: 네트워크 연결 문제. 다시 실행하면 이어서 진행합니다.") from exc
        except anthropic.AnthropicError as exc:  # e.g. no credentials found at request time
            raise PipelineError(f"{label}: {exc}\n{NO_CREDENTIALS}") from exc

        self.usage.add(message.usage)
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise PipelineError(f"{label}: Claude가 이 요청에 답하지 않았습니다 (분류: {category}).")
        if message.stop_reason == "max_tokens":
            raise PipelineError(f"{label}: 출력이 너무 길어 잘렸습니다. 이 절을 더 작게 나눠야 합니다.")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return _repair(json.loads(text))
        except json.JSONDecodeError as exc:
            raise PipelineError(f"{label}: 응답 JSON을 읽지 못했습니다 ({exc}).") from exc

    def _cached(self, name: str, make) -> dict:
        path = self.api_dir / name
        if path.is_file() and not self.force:
            return json.loads(path.read_text(encoding="utf-8"))
        data = make()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data

    # --- the three steps ----------------------------------------------------------

    def plan(self) -> dict:
        def make():
            self.log("  논문 전체 구조와 개요를 설계하는 중...")
            return self._call([self.document, {"type": "text", "text": prompt("plan.md")}], schema.PLAN_SCHEMA, "설계")

        return self._cached("plan.json", make)

    def section(self, plan: dict, index: int) -> dict:
        sec = plan["sections"][index]

        def make():
            nxt = sec.get("next_starts_with") or ""
            end = (
                f'"{nxt}"(으)로 시작하는 문단 바로 앞까지'
                if nxt
                else "본문의 끝까지 (참고문헌 목록은 빼고)"
            )
            instructions = prompt("section.md").format(
                id=sec["id"],
                number=sec["number"],
                title=sec["title"],
                title_ko=sec["title_ko"],
                pages=sec["pages"],
                starts_with=sec["starts_with"],
                end=end,
                figure_ids=", ".join(f"{f['id']}({f['label_original']})" for f in plan["figures"]) or "없음",
            )
            plan_text = json.dumps(plan, ensure_ascii=False)
            content = [
                self.document,
                {"type": "text", "text": "[설계]\n" + plan_text, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": instructions},
            ]
            return self._call(content, schema.SECTION_SCHEMA, f"절 {sec['number']} {sec['title_ko']}")

        return self._cached(f"sections/{index + 1:02d}-{sec['id']}.json", make)

    def locate(self, plan: dict) -> dict:
        figures = plan["figures"]
        if not figures:
            return {"figures": []}

        def make():
            self.log(f"  그림 {len(figures)}개의 위치를 재는 중...")
            pages = sorted({f["page"] for f in figures})
            content: list = []
            for page in pages:
                png = self.workdir / "pages" / f"p{page:03d}-grid.png"
                if not png.is_file():
                    continue
                content.append({"type": "text", "text": f"{page}쪽:"})
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(png.read_bytes()).decode(),
                        },
                    }
                )
            listing = "\n".join(
                f"- {f['id']}: {f['page']}쪽, {f['label_original']} — {f['caption_original'][:120]}" for f in figures
            )
            content.append({"type": "text", "text": prompt("locate.md").format(figures=listing)})
            return self._call(content, schema.LOCATE_SCHEMA, "그림 위치")

        return self._cached("locate.json", make)

    # --- everything ---------------------------------------------------------------

    def run(self, workers: int = 4) -> dict:
        start = time.time()
        plan = self.plan()
        sections = plan["sections"]
        self.log(f"  설계 완료: {len(sections)}개 절, 그림 {len(plan['figures'])}개, 용어 {len(plan['glossary'])}개")

        bodies: list[dict | None] = [None] * len(sections)

        def do(i: int):
            bodies[i] = self.section(plan, i)
            s = sections[i]
            self.log(f"  [{sum(b is not None for b in bodies)}/{len(sections)}] {s['number']} {s['title_ko']} 완료")

        if sections:
            # The first section writes the cache that the parallel ones read.
            do(0)
            with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = [pool.submit(do, i) for i in range(1, len(sections))]
                for future in cf.as_completed(futures):
                    future.result()
        boxes = {f["id"]: f for f in self.locate(plan)["figures"]}
        book = assemble(plan, bodies, boxes)
        minutes = (time.time() - start) / 60
        self.log(f"  API 사용량: {self.usage.describe(self.model)} · {minutes:.1f}분")
        return book


def assemble(plan: dict, bodies: list[dict], boxes: dict[str, dict]) -> dict:
    """Merge plan, section bodies and figure boxes into one book (not yet normalized)."""
    figure_ids = {f["id"] for f in plan["figures"]}
    sections = []
    for head, body in zip(plan["sections"], bodies):
        blocks = [
            b for b in body.get("blocks", []) if b.get("type") != "figure" or b.get("id") in figure_ids
        ]
        sections.append(
            {
                "id": head["id"],
                "number": head["number"],
                "title": head["title"],
                "title_ko": head["title_ko"],
                "summary": body.get("summary", ""),
                "blocks": blocks,
                "key_points": body.get("key_points", []),
            }
        )
    figures = []
    for fig in plan["figures"]:
        box = boxes.get(fig["id"], {})
        bbox = _clean_bbox(box.get("bbox") or [])
        page = box.get("page") or fig["page"]
        figures.append({**fig, "page": page, "bbox": bbox})
    return {
        "version": schema.BOOK_VERSION,
        "meta": plan["meta"],
        "intro": plan["intro"],
        "sections": sections,
        "figures": figures,
        "glossary": plan["glossary"],
        "summary": plan["summary"],
        "references": plan["references"],
    }


def _clean_bbox(bbox: list) -> list[float]:
    if len(bbox) != 4:
        return []
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in bbox)
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        return []
    return [round(v, 4) for v in (x0, y0, x1, y1)]
