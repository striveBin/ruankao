from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "study-html"
DOCS = OUT / "docs"
ASSETS = OUT / "assets"
PAGE_IMAGES = ASSETS / "pages"


TEXT_THRESHOLD = 80
IMAGE_ZOOM = 2.0
JPEG_QUALITY = 82
MAX_TOC_ITEMS = 180
SEARCH_CHARS_PER_PAGE = 2200
OCR_MIN_CHARS = 80
DEFAULT_OCR_LANG = "chi_sim+eng"

SENTENCE_END_RE = re.compile(r"[。！？；：.!?;:]$|[”’）》】]$")
LIST_START_RE = re.compile(
    r"^(?:"
    r"[（(]?[0-9一二三四五六七八九十]+[）).、．]"
    r"|[A-H][.．、)]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"
    r")"
)
SECTION_TITLE_RE = re.compile(
    r"^(?:第[一二三四五六七八九十0-9]+[章节篇部分]|[0-9]+(?:\.[0-9]+){0,3}\s+|[一二三四五六七八九十]+[、.．])"
)
NOISE_LINE_RE = re.compile(r"^(?:\d+|第\s*\d+\s*页|Page\s+\d+)$", re.I)
FITZ_IMPORT_ERROR = ""


def require_fitz() -> Any:
    """Import PyMuPDF lazily so helper commands can still run without it."""
    global FITZ_IMPORT_ERROR
    try:
        import fitz  # type: ignore
    except ModuleNotFoundError as exc:
        FITZ_IMPORT_ERROR = str(exc)
        raise SystemExit(
            "缺少 PyMuPDF / fitz，无法从 PDF 重建 HTML。请先运行："
            "python -m pip install -r requirements.txt"
        ) from exc
    return fitz


def clean_name(value: str) -> str:
    value = re.sub(r"\.pdf$", "", value, flags=re.I)
    value = re.sub(r"^[0-9]+[、.．]\s*", "", value)
    return value.strip()


def slug_for(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", clean_name(path.stem)).strip("-")
    digest = hashlib.sha1(str(path.relative_to(ROOT)).encode("utf-8")).hexdigest()[:8]
    return f"{stem[:64]}-{digest}" if stem else digest


def category_for(path: Path) -> str:
    rel = path.relative_to(ROOT)
    if len(rel.parts) == 1:
        return "根目录资料"
    return clean_name(rel.parts[0])


def kind_for(path: Path) -> str:
    name = path.name
    if "历年真题" in str(path):
        if "案例" in name:
            return "案例分析"
        return "选择题真题"
    if "官方教材" in str(path):
        if "教材" in name or "第3版" in name:
            return "教材/一本通"
        return "考点资料"
    if "机考" in str(path):
        return "机考说明"
    if "流程" in name or "报名" in name or "实名" in name:
        return "报考指南"
    return "学习资料"


def normalize_line(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_probably_title(line: str) -> bool:
    return len(line) <= 42 and bool(SECTION_TITLE_RE.search(line))


def is_noise_line(line: str) -> bool:
    return bool(NOISE_LINE_RE.fullmatch(line.strip()))


def is_sentence_end(line: str) -> bool:
    return bool(SENTENCE_END_RE.search(line.rstrip()))


def starts_new_paragraph(line: str) -> bool:
    return bool(LIST_START_RE.search(line)) or is_probably_title(line)


def needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return bool(re.search(r"[A-Za-z0-9]$", left) and re.search(r"^[A-Za-z0-9]", right))


def join_continuation(left: str, right: str) -> str:
    if left.endswith("-") and re.search(r"[A-Za-z]$", left[:-1]) and re.search(r"^[A-Za-z]", right):
        return left[:-1] + right
    return left + (" " if needs_space(left, right) else "") + right


def paragraphize_lines(lines: list[str]) -> list[str]:
    """Repair hard PDF line breaks while keeping titles/options readable."""
    cleaned = [line for line in (normalize_line(line) for line in lines) if line and not is_noise_line(line)]
    if not cleaned:
        return []

    paragraphs: list[str] = []
    current = cleaned[0]
    for line in cleaned[1:]:
        if starts_new_paragraph(line) or is_probably_title(current) or is_sentence_end(current):
            paragraphs.append(current)
            current = line
        else:
            current = join_continuation(current, line)
    paragraphs.append(current)
    return paragraphs


def text_blocks(page: Any) -> list[str]:
    data = page.get_text("dict", sort=True)
    blocks: list[str] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = normalize_line(text)
            if text:
                lines.append(text)
        blocks.extend(paragraphize_lines(lines))
    return blocks


def render_page(page: Any, target: Path, fitz_module: Any) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    matrix = fitz_module.Matrix(IMAGE_ZOOM, IMAGE_ZOOM)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(target, jpg_quality=JPEG_QUALITY)


def html_page_text(blocks: list[str]) -> str:
    parts = []
    for block in blocks:
        escaped = html.escape(block)
        if is_probably_title(block):
            parts.append(f"<h3>{escaped}</h3>")
        elif LIST_START_RE.search(block):
            parts.append(f'<p class="list-item">{escaped}</p>')
        else:
            parts.append(f"<p>{escaped}</p>")
    return '<div class="page-text">' + "\n".join(parts) + "</div>"


def html_fragment_text(blocks: list[str]) -> str:
    if not blocks:
        return ""
    text = "\n".join(blocks)
    return (
        '<details class="ocr-fragment"><summary>查看本页 PDF 内置的少量文字线索</summary>'
        f"<pre>{html.escape(text)}</pre></details>"
    )


def run_ocr(image_path: Path, lang: str) -> list[str]:
    """Run local Tesseract OCR when available; returns normalized paragraphs."""
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return []
    cmd = [tesseract, str(image_path), "stdout", "-l", lang, "--psm", "6"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return paragraphize_lines(result.stdout.splitlines())


def html_ocr_text(blocks: list[str]) -> str:
    if not blocks:
        return ""
    return '<div class="ocr-text"><h3>OCR 识别文本（待校对）</h3>' + html_page_text(blocks) + "</div>"


@dataclass
class DocMeta:
    title: str
    slug: str
    rel_path: str
    category: str
    kind: str
    pages: int
    text_pages: int
    image_pages: int
    ocr_pages: int
    chars: int
    href: str


@dataclass
class BuildOptions:
    enable_ocr: bool = False
    ocr_lang: str = DEFAULT_OCR_LANG
    limit: int = 0


STYLE = """
:root{color-scheme:light;--bg:#f8fafc;--panel:#fff;--text:#1e293b;--muted:#64748b;--line:#dbe3ee;--blue:#2563eb;--blue2:#1d4ed8;--green:#16835f;--amber:#a16207;--red:#b91c1c}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC",system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:1.78}
a{color:inherit;text-decoration:none}
.shell{display:grid;grid-template-columns:320px minmax(0,1fr);min-height:100vh}
.sidebar{position:sticky;top:0;height:100vh;overflow:auto;border-right:1px solid var(--line);background:#eef4fb;padding:24px}
.brand{font-size:24px;font-weight:800;line-height:1.2;margin:0 0 8px}
.sub{color:var(--muted);font-size:14px;margin:0 0 18px}
.search{width:100%;height:44px;border:1px solid var(--line);border-radius:8px;padding:0 12px;font-size:16px;background:#fff;color:var(--text)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 20px}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 10px;color:var(--muted);font-size:13px;cursor:pointer}
.chip.active{background:var(--blue);border-color:var(--blue);color:#fff}
.main{padding:32px;max-width:1180px;width:100%}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.stat b{display:block;font-size:26px;line-height:1.1}.stat span{color:var(--muted);font-size:13px}
.library-note{background:#fff;border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:10px;padding:14px 16px;margin:0 0 24px;color:#334155}
.section-title{margin:28px 0 12px;font-size:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;transition:.18s ease;min-height:148px}
.card:hover{border-color:#94a3b8;transform:translateY(-1px);box-shadow:0 8px 24px rgba(15,23,42,.08)}
.card h3{font-size:16px;line-height:1.35;margin:0 0 8px}.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.badge{display:inline-flex;align-items:center;border-radius:999px;background:#eef2ff;color:#3730a3;padding:3px 8px;font-size:12px;line-height:1.5}.badge.scan{background:#fff7ed;color:#9a3412}.badge.text{background:#ecfdf5;color:#047857}.badge.warn{background:#fef2f2;color:var(--red)}
.path{color:var(--muted);font-size:12px;line-height:1.5;word-break:break-all}.doc-header{border-bottom:1px solid var(--line);background:#fff;padding:24px 32px;position:sticky;top:0;z-index:10;box-shadow:0 2px 16px rgba(15,23,42,.04)}
.doc-header h1{font-size:24px;line-height:1.25;margin:0 0 8px}.back{display:inline-flex;align-items:center;min-height:36px;margin-bottom:8px;color:var(--blue);font-weight:700}.reader{max-width:940px;margin:0 auto;padding:28px 20px 80px}
.notice{background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;border-radius:10px;padding:12px 14px;margin:0 0 18px;color:#713f12}
.page{background:#fff;border:1px solid var(--line);border-radius:10px;margin:0 0 18px;padding:22px;box-shadow:0 2px 10px rgba(15,23,42,.04)}.page h2{font-size:15px;color:var(--muted);margin:0 0 14px;border-bottom:1px solid var(--line);padding-bottom:8px}.page h3{font-size:20px;line-height:1.42;margin:18px 0 8px}.page p{margin:0 0 12px;text-align:justify}.page-text{font-size:17px;letter-spacing:.01em}.page-text .list-item{text-align:left;padding-left:.25rem}.page-img{display:block;width:100%;height:auto;border-radius:6px;background:#f1f5f9;border:1px solid #e2e8f0}.ocr-text{margin-top:14px;border:1px solid #bfdbfe;border-left:4px solid var(--blue);border-radius:10px;padding:14px;background:#eff6ff}.ocr-text h3{margin-top:0}.ocr-fragment{margin-top:12px;border:1px dashed var(--line);border-radius:8px;padding:10px;background:#f8fafc}.ocr-fragment summary{cursor:pointer;color:var(--blue);font-weight:700}.ocr-fragment pre{white-space:pre-wrap;word-break:break-word;margin:10px 0 0;font-family:inherit;color:#475569}.toc{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 18px}.toc h2{margin:0 0 10px;font-size:16px}.toc a{display:block;color:var(--blue);padding:3px 0}.empty{color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:8px;padding:24px}
@media(max-width:840px){.shell{display:block}.sidebar{position:static;height:auto}.main{padding:20px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.doc-header{position:static;padding:18px}.reader{padding:18px 12px 56px}.page{padding:14px}.page-text{font-size:16px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
"""


INDEX_JS = """
const search = document.querySelector('#search');
const cards = [...document.querySelectorAll('[data-card]')];
const chips = [...document.querySelectorAll('[data-filter]')];
let active = '全部';
function apply(){
  const q = search.value.trim().toLowerCase();
  cards.forEach(card => {
    const okFilter = active === '全部' || card.dataset.category === active || card.dataset.kind === active || (active === '需要OCR' && card.dataset.scan === 'true');
    const okSearch = !q || card.dataset.search.toLowerCase().includes(q);
    card.style.display = okFilter && okSearch ? '' : 'none';
  });
}
search.addEventListener('input', apply);
chips.forEach(chip => chip.addEventListener('click', () => {
  active = chip.dataset.filter;
  chips.forEach(c => c.classList.toggle('active', c === chip));
  apply();
}));
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_doc(pdf: Path, options: BuildOptions, fitz_module: Any, quality: list[dict[str, Any]]) -> DocMeta:
    rel = pdf.relative_to(ROOT)
    rel_posix = rel.as_posix()
    title = clean_name(pdf.stem)
    slug = slug_for(pdf)
    doc_dir = PAGE_IMAGES / slug
    doc = fitz_module.open(pdf)
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        toc = []
    content_parts: list[str] = []
    text_pages = image_pages = ocr_pages = chars = 0
    page_issues: list[dict[str, Any]] = []
    search_chunks: list[str] = []

    if toc:
        toc_links = []
        for level, label, page_no in toc[:MAX_TOC_ITEMS]:
            indent = (level - 1) * 14
            toc_links.append(
                f'<a style="padding-left:{indent}px" href="#p{page_no}">{html.escape(label)}</a>'
            )
        content_parts.append('<nav class="toc"><h2>目录</h2>' + "\n".join(toc_links) + "</nav>")

    for idx in range(1, len(doc) + 1):
        try:
            page = doc.load_page(idx - 1)
        except Exception as exc:
            body = f'<div class="empty">这一页 PDF 结构损坏，未能转换：{html.escape(str(exc))}</div>'
            content_parts.append(f'<section class="page" id="p{idx}"><h2>第 {idx} 页</h2>{body}</section>')
            continue
        try:
            blocks = text_blocks(page)
        except Exception:
            try:
                fallback = page.get_text("text", sort=True) or ""
            except Exception:
                fallback = ""
            blocks = paragraphize_lines(fallback.splitlines())
        page_text = "\n".join(blocks).strip()
        chars += len(page_text)
        if page_text:
            search_chunks.append(page_text[:SEARCH_CHARS_PER_PAGE])
        if len(page_text) >= TEXT_THRESHOLD:
            text_pages += 1
            body = html_page_text(blocks)
        else:
            image_pages += 1
            image_path = doc_dir / f"p{idx:04d}.jpg"
            try:
                render_page(page, image_path, fitz_module)
                rel_img = image_path.relative_to(OUT).as_posix()
                ocr_blocks = run_ocr(image_path, options.ocr_lang) if options.enable_ocr else []
                if len("\n".join(ocr_blocks).strip()) >= OCR_MIN_CHARS:
                    ocr_pages += 1
                    search_chunks.append("\n".join(ocr_blocks)[:SEARCH_CHARS_PER_PAGE])
                else:
                    page_issues.append({"page": idx, "type": "needs_ocr", "chars": len(page_text)})
                body = (
                    f'<img class="page-img" loading="lazy" '
                    f'src="../{html.escape(rel_img)}" alt="{html.escape(title)} 第 {idx} 页">'
                    + html_ocr_text(ocr_blocks)
                    + html_fragment_text(blocks)
                )
            except Exception as exc:
                body = f'<div class="empty">这一页未能渲染：{html.escape(str(exc))}</div>' + html_fragment_text(blocks)
        content_parts.append(f'<section class="page" id="p{idx}"><h2>第 {idx} 页</h2>{body}</section>')

    if not content_parts:
        content_parts.append('<div class="empty">这个 PDF 没有可转换的页面。</div>')

    notice = ""
    if image_pages:
        notice = (
            '<div class="notice">本资料包含扫描/图片页：已保留高清页面图；如果 PDF 内有少量文字线索，会折叠显示在页面下方，方便后续 OCR 或人工校对。</div>'
        )

    doc_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - 软考学习资料库</title>
  <style>{STYLE}</style>
</head>
<body>
  <header class="doc-header">
    <a class="back" href="../index.html">返回资料库</a>
    <h1>{html.escape(title)}</h1>
    <div class="path">{html.escape(rel_posix)}</div>
    <div class="meta">
      <span class="badge">{len(doc)} 页</span>
      <span class="badge text">文字页 {text_pages}</span>
      <span class="badge scan">图像页 {image_pages}</span>
      <span class="badge text">OCR页 {ocr_pages}</span>
    </div>
  </header>
  <main class="reader">
    {notice}
    {''.join(content_parts)}
  </main>
</body>
</html>
"""
    write_text(DOCS / f"{slug}.html", doc_html)

    search_text = "\n\n".join(search_chunks)
    write_text(DOCS / f"{slug}.search.txt", search_text)
    meta = DocMeta(
        title=title,
        slug=slug,
        rel_path=rel_posix,
        category=category_for(pdf),
        kind=kind_for(pdf),
        pages=len(doc),
        text_pages=text_pages,
        image_pages=image_pages,
        ocr_pages=ocr_pages,
        chars=chars,
        href=f"docs/{slug}.html",
    )
    quality.append({
        "title": title,
        "slug": slug,
        "rel_path": rel_posix,
        "pages": len(doc),
        "text_pages": text_pages,
        "image_pages": image_pages,
        "ocr_pages": ocr_pages,
        "chars": chars,
        "issues": page_issues,
    })
    return meta


def build_index(docs: list[DocMeta]) -> None:
    categories = ["全部", "需要OCR"] + sorted({d.category for d in docs}) + sorted({d.kind for d in docs})
    chips = "\n".join(
        f'<button class="chip{" active" if c == "全部" else ""}" data-filter="{html.escape(c)}">{html.escape(c)}</button>'
        for c in categories
    )
    grouped: dict[str, list[DocMeta]] = {}
    for doc in docs:
        grouped.setdefault(doc.category, []).append(doc)

    sections = []
    for category, items in grouped.items():
        cards = []
        for d in sorted(items, key=lambda x: x.rel_path):
            search_blob = f"{d.title} {d.rel_path} {d.category} {d.kind}"
            scan_ratio = d.image_pages / d.pages if d.pages else 0
            quality_badge = '<span class="badge warn">需要OCR/校对</span>' if d.image_pages else '<span class="badge text">可读文本</span>'
            cards.append(
                f"""<a class="card" data-card data-category="{html.escape(d.category)}" data-kind="{html.escape(d.kind)}" data-scan="{str(bool(d.image_pages)).lower()}" data-search="{html.escape(search_blob)}" href="{html.escape(d.href)}">
  <h3>{html.escape(d.title)}</h3>
  <div class="path">{html.escape(d.rel_path)}</div>
  <div class="meta">
    <span class="badge">{d.kind}</span>
    <span class="badge">{d.pages} 页</span>
    <span class="badge text">文字 {d.text_pages}</span>
    <span class="badge scan">图像 {d.image_pages}</span>
    <span class="badge text">OCR {d.ocr_pages}</span>
    {quality_badge}
    <span class="badge">图像占比 {scan_ratio:.0%}</span>
  </div>
</a>"""
            )
        sections.append(
            f'<h2 class="section-title">{html.escape(category)}</h2><div class="grid">{"".join(cards)}</div>'
        )

    index = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>软考学习资料库</title>
  <style>{STYLE}</style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <h1 class="brand">软考学习资料库</h1>
      <p class="sub">PDF 已拆成 HTML 阅读页；文字层会修复硬换行，扫描件保留页面图并标记为后续 OCR/校对对象。</p>
      <input id="search" class="search" type="search" placeholder="搜索标题、年份、类型">
      <div class="filters">{chips}</div>
    </aside>
    <main class="main">
      <section class="stats">
        <div class="stat"><b>{len(docs)}</b><span>PDF 资料</span></div>
        <div class="stat"><b>{sum(d.pages for d in docs)}</b><span>总页数</span></div>
        <div class="stat"><b>{sum(d.text_pages for d in docs)}</b><span>文字页</span></div>
        <div class="stat"><b>{sum(d.image_pages for d in docs)}</b><span>图像页</span></div>
        <div class="stat"><b>{sum(d.ocr_pages for d in docs)}</b><span>OCR 页</span></div>
      </section>
      <div class="library-note">建议优先处理“需要OCR”资料：这些页面已保留原始页面图，可在后续引入中文 OCR 后自动生成可复制文本，再进行人工校对。</div>
      {''.join(sections)}
    </main>
  </div>
  <script>{INDEX_JS}</script>
</body>
</html>
"""
    write_text(OUT / "index.html", index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static soft-exam PDF study library.")
    parser.add_argument("--ocr", action="store_true", help="Run local Tesseract OCR for scanned/image pages when tesseract is installed.")
    parser.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG, help="Tesseract language list, e.g. chi_sim+eng.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N PDFs for smoke testing.")
    return parser.parse_args()


def write_quality_report(docs: list[DocMeta], quality: list[dict[str, Any]]) -> None:
    summary = {
        "documents": len(docs),
        "pages": sum(d.pages for d in docs),
        "text_pages": sum(d.text_pages for d in docs),
        "image_pages": sum(d.image_pages for d in docs),
        "ocr_pages": sum(d.ocr_pages for d in docs),
        "documents_with_issues": sum(1 for item in quality if item["issues"]),
        "page_issues": sum(len(item["issues"]) for item in quality),
    }
    write_text(
        OUT / "quality-report.json",
        json.dumps({"summary": summary, "documents": quality}, ensure_ascii=False, indent=2),
    )


def main() -> None:
    args = parse_args()
    options = BuildOptions(enable_ocr=args.ocr, ocr_lang=args.ocr_lang, limit=args.limit)
    fitz_module = require_fitz()
    DOCS.mkdir(parents=True, exist_ok=True)
    PAGE_IMAGES.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(
        p for p in ROOT.rglob("*.pdf")
        if OUT not in p.parents and ".agents" not in p.parts and ".claude" not in p.parts
    )
    if options.limit:
        pdfs = pdfs[:options.limit]
    if options.enable_ocr and not shutil.which("tesseract"):
        print("WARNING: --ocr 已启用，但未找到 tesseract；将只渲染页面图，不生成 OCR 文本。", flush=True)
    docs: list[DocMeta] = []
    quality: list[dict[str, Any]] = []
    for index, pdf in enumerate(pdfs, start=1):
        print(f"[{index}/{len(pdfs)}] {pdf.relative_to(ROOT)}", flush=True)
        try:
            docs.append(build_doc(pdf, options, fitz_module, quality))
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
    build_index(docs)
    manifest = [doc.__dict__ for doc in docs]
    write_text(OUT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    write_quality_report(docs, quality)
    print(f"Built {len(docs)} documents into {OUT}")


if __name__ == "__main__":
    main()
