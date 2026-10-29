"""PDF side of the pipeline: page images, text, and figure crops.

``prepare`` lays out a work directory that a person (or Claude Code) can read
page by page::

    work/<slug>/
      source.pdf            the paper, or the selected page range of it
      info.json             page count, text layer, figure captions, graphics boxes
      pages/p001.png        whole page, long edge about 1600 px
      pages/p001-top.png    upper and lower halves at twice the resolution,
      pages/p001-bot.png    for reading small print and dense equations
      pages/p001-grid.png   the page with a 0.1 grid, for measuring figure boxes
      text/p001.txt         the text layer (empty for scanned pages)

Figure boxes in a book are fractions of the page, origin top left. ``crop``
renders that box; on born-digital PDFs it first snaps the box outwards to the
drawings and images it touches, so a roughly measured box still yields the
whole figure.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path

import pymupdf

CAPTION_RE = re.compile(r"^\s*(FIG\.?|Fig\.?|FIGURE|Figure|그림)\s*(\d+)", re.MULTILINE)
VIEW_EDGE = 1600  # px, long edge of the page images written by prepare
CROP_EDGE = 2000  # px, cap on the long edge of a figure crop


def parse_pages(spec: str | None, count: int) -> list[int]:
    """'1-3,7' -> [0, 1, 2, 6] (0-based). None or '' -> every page."""
    if not spec:
        return list(range(count))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a or 1), int(b or count)
        else:
            start = end = int(part)
        if not (1 <= start <= end <= count):
            raise ValueError(f"쪽 범위 '{part}'가 PDF(1~{count}쪽) 밖입니다.")
        pages.extend(range(start - 1, end))
    return sorted(set(pages))


def _zoom_for(rect: pymupdf.Rect, edge: int) -> float:
    return edge / max(rect.width, rect.height)


def _png(pix: pymupdf.Pixmap, path: Path) -> None:
    path.write_bytes(pix.tobytes("png"))


def _draw_grid(page: pymupdf.Page) -> None:
    """Draw a labelled 0.1 grid (and faint 0.05 lines) onto the page."""
    rect = page.rect
    w, h = rect.width, rect.height
    shape = page.new_shape()
    for i in range(1, 20):
        f = i / 20
        major = i % 2 == 0
        shape.draw_line((rect.x0 + f * w, rect.y0), (rect.x0 + f * w, rect.y1))
        shape.draw_line((rect.x0, rect.y0 + f * h), (rect.x1, rect.y0 + f * h))
        shape.finish(
            color=(0.85, 0.1, 0.2) if major else (0.2, 0.4, 0.85),
            width=0.6 if major else 0.4,
            stroke_opacity=0.55 if major else 0.35,
            dashes=None if major else "[2 2] 0",
        )
    shape.commit()
    for i in range(1, 10):
        f = i / 10
        label = f"{f:.1f}"
        for x, y in ((rect.x0 + f * w + 1.5, rect.y0 + 8), (rect.x0 + f * w + 1.5, rect.y1 - 3)):
            page.insert_text((x, y), label, fontsize=7, color=(0.85, 0.1, 0.2))
        for x, y in ((rect.x0 + 2, rect.y0 + f * h - 2), (rect.x1 - 14, rect.y0 + f * h - 2)):
            page.insert_text((x, y), label, fontsize=7, color=(0.85, 0.1, 0.2))


def graphics_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Boxes of pictures and vector drawings, without page-sized scans and rules."""
    area = page.rect.width * page.rect.height
    rects: list[pymupdf.Rect] = []
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if r.is_empty or r.width < 8 or r.height < 8:
            continue
        if r.get_area() > 0.6 * area:  # a scanned page, not a figure
            continue
        rects.append(r)
    try:
        clusters = page.cluster_drawings()
    except Exception:  # very old PyMuPDF or odd drawings
        clusters = [d["rect"] for d in page.get_drawings()]
    for r in clusters:
        r = pymupdf.Rect(r) & page.rect
        if r.is_empty or r.get_area() < 120:
            continue
        if r.height < 3 and r.width > 0.4 * page.rect.width:  # header/footer rule
            continue
        if r.width < 3 and r.height > 0.4 * page.rect.height:  # column rule
            continue
        rects.append(r)
    return rects


def _norm(rect: pymupdf.Rect, page: pymupdf.Page) -> list[float]:
    p = page.rect
    return [
        round((rect.x0 - p.x0) / p.width, 4),
        round((rect.y0 - p.y0) / p.height, 4),
        round((rect.x1 - p.x0) / p.width, 4),
        round((rect.y1 - p.y0) / p.height, 4),
    ]


def _denorm(bbox: list[float], page: pymupdf.Page) -> pymupdf.Rect:
    p = page.rect
    x0, y0, x1, y1 = bbox
    return pymupdf.Rect(p.x0 + x0 * p.width, p.y0 + y0 * p.height, p.x0 + x1 * p.width, p.y0 + y1 * p.height)


def prepare(pdf: str | Path, workdir: str | Path, pages: str | None = None) -> dict:
    """Write page images, text and info.json for ``pdf`` into ``workdir``."""
    pdf, workdir = Path(pdf), Path(workdir)
    (workdir / "pages").mkdir(parents=True, exist_ok=True)
    (workdir / "text").mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf) as original:
        if original.needs_pass:
            raise ValueError("암호가 걸린 PDF는 처리할 수 없습니다.")
        selected = parse_pages(pages, original.page_count)
        if len(selected) == original.page_count:
            shutil.copyfile(pdf, workdir / "source.pdf")
        else:
            with pymupdf.open() as subset:
                for index in selected:
                    subset.insert_pdf(original, from_page=index, to_page=index)
                subset.save(workdir / "source.pdf")
        metadata = {k: v for k, v in (original.metadata or {}).items() if v}

    info: dict = {
        "source": pdf.name,
        "page_numbers_in_original": [i + 1 for i in selected],
        "metadata": metadata,
        "pages": [],
        "captions": [],
    }
    with pymupdf.open(workdir / "source.pdf") as doc, pymupdf.open(workdir / "source.pdf") as gridded:
        for index, page in enumerate(doc):
            stem = f"p{index + 1:03d}"
            rect = page.rect
            zoom = _zoom_for(rect, VIEW_EDGE)
            _png(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)), workdir / "pages" / f"{stem}.png")
            half_zoom = _zoom_for(pymupdf.Rect(0, 0, rect.width, rect.height / 2), VIEW_EDGE)
            top = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height * 0.55)
            bottom = pymupdf.Rect(rect.x0, rect.y0 + rect.height * 0.45, rect.x1, rect.y1)
            m = pymupdf.Matrix(half_zoom, half_zoom)
            _png(page.get_pixmap(matrix=m, clip=top), workdir / "pages" / f"{stem}-top.png")
            _png(page.get_pixmap(matrix=m, clip=bottom), workdir / "pages" / f"{stem}-bot.png")

            grid_page = gridded[index]
            _draw_grid(grid_page)
            _png(grid_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)), workdir / "pages" / f"{stem}-grid.png")

            text = page.get_text("text", sort=True)
            (workdir / "text" / f"{stem}.txt").write_text(text, encoding="utf-8")
            for block in page.get_text("blocks", sort=True):
                match = CAPTION_RE.match(block[4])
                if match:
                    info["captions"].append(
                        {
                            "page": index + 1,
                            "label": f"{match.group(1)} {match.group(2)}",
                            "number": int(match.group(2)),
                            "bbox": _norm(pymupdf.Rect(block[:4]), page),
                            "text": " ".join(block[4].split())[:160],
                        }
                    )
            info["pages"].append(
                {
                    "page": index + 1,
                    "size_pt": [round(rect.width, 1), round(rect.height, 1)],
                    "chars": len(text.strip()),
                    "graphics": [_norm(r, page) for r in graphics_rects(page)],
                }
            )
    chars = [p["chars"] for p in info["pages"]]
    info["page_count"] = len(chars)
    info["text_layer"] = bool(chars) and sum(c > 200 for c in chars) >= max(1, len(chars) // 2)
    (workdir / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def figure_rect(page: pymupdf.Page, bbox: list[float]) -> pymupdf.Rect:
    """The page area for a figure box, snapped outwards to nearby graphics."""
    target = _denorm(bbox, page)
    w, h = page.rect.width, page.rect.height
    grown = pymupdf.Rect(target.x0 - 0.02 * w, target.y0 - 0.02 * h, target.x1 + 0.02 * w, target.y1 + 0.02 * h)
    rect = pymupdf.Rect(target)
    picked = [r for r in graphics_rects(page) if (r & grown).get_area() >= 0.5 * r.get_area()]
    for r in picked:
        rect |= r
    if picked:
        # Axis labels and other short text sitting right next to the drawings.
        drawn = pymupdf.Rect(picked[0])
        for r in picked[1:]:
            drawn |= r
        near = pymupdf.Rect(drawn.x0 - 10, drawn.y0 - 10, drawn.x1 + 10, drawn.y1 + 10)
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
            block = pymupdf.Rect(x0, y0, x1, y1)
            if len(text.strip()) > 60 or CAPTION_RE.match(text) or block.is_empty:
                continue
            if block.intersects(near) and (block & grown).get_area() >= 0.5 * block.get_area():
                rect |= block
    pad = 4
    return pymupdf.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad) & page.rect


def crop(doc: pymupdf.Document, page_number: int, bbox: list[float] | None) -> tuple[bytes, str]:
    """Render a figure as (image bytes, mime type). No box -> the whole page."""
    page = doc[page_number - 1]
    clip = figure_rect(page, bbox) if bbox else page.rect
    native = 72.0
    for info in page.get_image_info():  # keep a scan's own resolution
        r = pymupdf.Rect(info["bbox"])
        if r.width > 0 and info.get("width"):
            native = max(native, 72.0 * info["width"] / r.width)
    zoom = min(max(3.0, native / 72.0), CROP_EDGE / max(clip.width, clip.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
    data, mime = pix.tobytes("png"), "image/png"
    if len(data) > 700_000:
        data, mime = pix.tobytes("jpeg", jpg_quality=85), "image/jpeg"
    return data, mime


def figure_images(workdir: str | Path, figures: list[dict], save_dir: Path | None = None) -> dict[str, str]:
    """Data URIs for every figure of a book; optionally also saved as files."""
    workdir = Path(workdir)
    source = workdir / "source.pdf"
    if not source.is_file() or not figures:
        return {}
    uris: dict[str, str] = {}
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(source) as doc:
        for fig in figures:
            if not 1 <= fig["page"] <= doc.page_count:
                continue
            data, mime = crop(doc, fig["page"], fig["bbox"] or None)
            uris[fig["id"]] = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            if save_dir:
                ext = "png" if mime == "image/png" else "jpg"
                (save_dir / f"{fig['id']}.{ext}").write_bytes(data)
    return uris
