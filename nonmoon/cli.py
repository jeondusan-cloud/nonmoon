"""Command line: ``nonmoon build paper.pdf`` and friends."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

from . import __version__, book as books, pdfprep
from .markup import protect_math

PACKAGE_PROFILE = Path(__file__).parent / "prompts" / "profile.md"


def slug_for(pdf: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", pdf.stem).strip("-_")
    stem = re.sub(r"[-_]{2,}", "-", stem)
    return stem.lower() or "paper"


def read_profile(path: str | None) -> str:
    candidates = [Path(path)] if path else [Path("profile.md"), PACKAGE_PROFILE]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    if path:
        raise SystemExit(f"독자 프로필 파일을 찾을 수 없습니다: {path}")
    return ""


def render_to(workdir: Path, out: Path, *, artifact: bool, profile: str) -> Path:
    from .render import render_book

    book = books.validate(books.load(workdir))
    info_file = workdir / "info.json"
    source_name = json.loads(info_file.read_text(encoding="utf-8")).get("source", "") if info_file.is_file() else ""
    images = pdfprep.figure_images(workdir, book["figures"], save_dir=workdir / "figures")
    html = render_book(book, images, artifact=artifact, profile=profile, source_name=source_name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


# --- commands ------------------------------------------------------------------


def cmd_prepare(args) -> int:
    pdf = Path(args.pdf)
    workdir = Path(args.work or Path("work") / slug_for(pdf))
    info = pdfprep.prepare(pdf, workdir, pages=args.pages)
    layer = "있음" if info["text_layer"] else "없음 (스캔본: 쪽 이미지를 보고 읽어야 함)"
    print(f"{workdir}: {info['page_count']}쪽, 텍스트 레이어 {layer}, 그림 캡션 후보 {len(info['captions'])}개")
    return 0


def cmd_render(args) -> int:
    workdir = Path(args.workdir)
    out = Path(args.output or Path("output") / f"{workdir.name}{'.artifact' if args.artifact else ''}.html")
    try:
        path = render_to(workdir, out, artifact=args.artifact, profile=read_profile(args.profile))
    except books.BookError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"교과서를 만들었습니다: {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_build(args) -> int:
    from . import llm

    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"PDF를 찾을 수 없습니다: {pdf}", file=sys.stderr)
        return 1
    workdir = Path(args.work or Path("work") / slug_for(pdf))
    profile = read_profile(args.profile)

    print(f"[1/3] PDF 준비: {pdf.name}")
    if args.force or not (workdir / "source.pdf").is_file():
        info = pdfprep.prepare(pdf, workdir, pages=args.pages)
        print(f"  {info['page_count']}쪽 · 텍스트 레이어 {'있음' if info['text_layer'] else '없음(스캔본)'}")
    else:
        print(f"  이미 준비된 작업 폴더를 씁니다: {workdir}")
    if args.dry_run:
        print("--dry-run: API 호출 없이 멈춥니다.")
        return 0

    print(f"[2/3] Claude({args.model}, effort={args.effort})가 번역과 해설을 쓰는 중 (몇 분 걸립니다)")
    try:
        pipeline = llm.Pipeline(
            workdir, model=args.model, effort=args.effort, profile=profile, force=args.force
        )
        book = pipeline.run(workers=args.workers)
    except llm.PipelineError as exc:
        print(f"\n중단: {exc}", file=sys.stderr)
        return 1
    normalized = books.normalize(book)
    books.write_json(normalized, workdir / "book.json")
    found = books.problems(normalized)
    if found:
        print("  형식 경고:\n" + "\n".join(f"    - {p}" for p in found[:20]), file=sys.stderr)

    print("[3/3] 교과서 HTML 만드는 중")
    out = Path(args.output or Path("output") / f"{workdir.name}.html")
    try:
        path = render_to(workdir, out, artifact=False, profile=profile)
    except books.BookError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"\n완성: {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def _math_items(book: dict) -> list[tuple[str, str, bool]]:
    """Every TeX string in the book: (where, tex, display)."""
    items: list[tuple[str, str, bool]] = []

    def text(where: str, value: str):
        _, found = protect_math(value or "")
        items.extend((where, tex, display) for tex, display in found)

    def walk(where: str, value):
        if isinstance(value, str):
            text(where, value)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(f"{where}[{i}]", v)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k == "latex":
                    items.append((f"{where}.latex", v, True))
                elif k == "symbol":
                    items.append((f"{where}.symbol", v, False))
                else:
                    walk(f"{where}.{k}" if where else k, v)

    walk("", book)
    return items


def _stray_dollars(book: dict) -> list[str]:
    found = []

    def walk(where, value):
        if isinstance(value, str):
            rest, _ = protect_math(value)
            if re.search(r"(?<!\\)\$", rest):
                found.append(f"{where}: 짝이 맞지 않는 $ (수식 구분자 확인)")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(f"{where}[{i}]", v)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in ("latex", "symbol"):
                    walk(f"{where}.{k}" if where else k, v)

    walk("", book)
    return found


KATEX_CHECK_JS = r"""
const katex = require(process.argv[2]);
const items = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const errors = [];
for (const [where, tex, display] of items) {
  try { katex.renderToString(tex, {displayMode: display, throwOnError: true, strict: 'ignore', macros: {'\\R': '\\mathbb{R}'}}); }
  catch (e) { errors.push([where, tex, String(e.message || e)]); }
}
process.stdout.write(JSON.stringify(errors));
"""


def cmd_check(args) -> int:
    workdir = Path(args.workdir)
    try:
        book = books.load(workdir)
    except books.BookError as exc:
        print(exc, file=sys.stderr)
        return 1
    problems = books.problems(book)
    warnings = _stray_dollars(book)

    items = _math_items(book)
    node = shutil.which("node")
    if node:
        katex = Path(__file__).parent / "assets" / "katex" / "katex.min.js"
        with tempfile.TemporaryDirectory() as tmp:
            script, data = Path(tmp) / "check.js", Path(tmp) / "items.json"
            script.write_text(KATEX_CHECK_JS, encoding="utf-8")
            data.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([node, str(script), str(katex), str(data)], capture_output=True, text=True)
        if result.returncode == 0:
            for where, tex, message in json.loads(result.stdout or "[]"):
                problems.append(f"{where}: 수식 오류 — {message}\n      {tex[:160]}")
        else:
            warnings.append("node로 수식 검사를 하지 못했습니다: " + result.stderr.strip()[:200])
    else:
        warnings.append("node가 없어 수식(KaTeX) 검사를 건너뜁니다.")

    corpus = json.dumps(book["sections"], ensure_ascii=False)
    for g in book["glossary"]:
        if g["ko"] and g["ko"] not in corpus:
            warnings.append(f"용어집 '{g['ko']}'가 본문에 한 번도 나오지 않습니다 (표기를 본문과 맞추세요).")
    if books.translated(book):
        for si, s in enumerate(book["sections"]):
            for bi, b in enumerate(s["blocks"]):
                if b["type"] == "paragraph" and b["original"].strip() and not b["translation"].strip():
                    warnings.append(f"sections[{si}].blocks[{bi}]: 번역이 비어 있습니다.")
    for fig in book["figures"]:
        if not fig["bbox"]:
            warnings.append(f"{fig['id']}: bbox가 없어 쪽 전체가 그림으로 들어갑니다.")

    print(f"절 {len(book['sections'])}개 · 블록 {sum(len(s['blocks']) for s in book['sections'])}개 · 수식 {len(items)}개 · 그림 {len(book['figures'])}개")
    for w in warnings:
        print("  경고:", w)
    for p in problems:
        print("  오류:", p)
    if not problems:
        print("문제 없음." if not warnings else "오류 없음 (경고만 있음).")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nonmoon", description="물리학 논문 PDF를 한국어 교과서(번역 + 해설) HTML로 바꿉니다."
    )
    parser.add_argument("--version", action="version", version=f"nonmoon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="PDF → 교과서 HTML (Claude API 사용)")
    p.add_argument("pdf")
    p.add_argument("-o", "--output", help="결과 HTML 경로 (기본: output/<이름>.html)")
    p.add_argument("--work", help="작업 폴더 (기본: work/<이름>)")
    p.add_argument("--model", default="claude-opus-5-5", help="Claude 모델 (기본: claude-opus-5-5)")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--pages", help="처리할 쪽 범위, 예: 1-8 또는 1-3,5")
    p.add_argument("--profile", help="독자 프로필 파일 (기본: ./profile.md 또는 내장 프로필)")
    p.add_argument("--workers", type=int, default=4, help="동시에 처리할 절 수")
    p.add_argument("--force", action="store_true", help="저장된 중간 결과를 무시하고 처음부터")
    p.add_argument("--open", action="store_true", help="끝나면 브라우저로 열기")
    p.add_argument("--dry-run", action="store_true", help="PDF 준비까지만 하고 API는 부르지 않기")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("prepare", help="PDF → 쪽 이미지·텍스트 (작업 폴더 만들기)")
    p.add_argument("pdf")
    p.add_argument("--work")
    p.add_argument("--pages")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("render", help="작업 폴더의 book.yaml/json → 교과서 HTML")
    p.add_argument("workdir")
    p.add_argument("-o", "--output")
    p.add_argument("--artifact", action="store_true", help="claude.ai Artifact로 게시할 형태로 만들기")
    p.add_argument("--profile")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("check", help="book 형식·수식·용어 검사")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)
