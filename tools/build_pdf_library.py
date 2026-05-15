from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "study-html"
DOCS = OUT / "docs"
ASSETS = OUT / "assets"
PAGE_IMAGES = ASSETS / "pages"


TEXT_THRESHOLD = 80
IMAGE_ZOOM = 2.0
JPEG_QUALITY = 82


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
    parts = path.parts
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


def text_blocks(page: fitz.Page) -> list[str]:
    data = page.get_text("dict")
    blocks: list[str] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                lines.append(text)
        if lines:
            blocks.append("\n".join(lines))
    return blocks


def render_page(page: fitz.Page, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    matrix = fitz.Matrix(IMAGE_ZOOM, IMAGE_ZOOM)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(target, jpg_quality=JPEG_QUALITY)


def html_page_text(blocks: list[str]) -> str:
    parts = []
    for block in blocks:
        escaped = html.escape(block)
        if len(block) <= 36 and re.search(r"第[一二三四五六七八九十0-9]+[章节篇]|^[0-9.]+\\s", block):
            parts.append(f"<h3>{escaped}</h3>")
        else:
            parts.append(f"<p>{escaped.replace(chr(10), '<br>')}</p>")
    return "\n".join(parts)


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
    chars: int
    href: str


STYLE = """
:root{color-scheme:light;--bg:#f8fafc;--panel:#fff;--text:#1e293b;--muted:#64748b;--line:#dbe3ee;--blue:#2563eb;--blue2:#1d4ed8;--green:#16835f;--amber:#a16207}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei","PingFang SC",system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:1.7}
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
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}
.stat b{display:block;font-size:26px;line-height:1.1}
.stat span{color:var(--muted);font-size:13px}
.section-title{margin:28px 0 12px;font-size:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;transition:.18s ease;min-height:148px}
.card:hover{border-color:#94a3b8;transform:translateY(-1px);box-shadow:0 8px 24px rgba(15,23,42,.08)}
.card h3{font-size:16px;line-height:1.35;margin:0 0 8px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.badge{display:inline-flex;align-items:center;border-radius:999px;background:#eef2ff;color:#3730a3;padding:3px 8px;font-size:12px}
.badge.scan{background:#fff7ed;color:#9a3412}.badge.text{background:#ecfdf5;color:#047857}
.path{color:var(--muted);font-size:12px;line-height:1.5;word-break:break-all}
.doc-header{border-bottom:1px solid var(--line);background:#fff;padding:24px 32px;position:sticky;top:0;z-index:10}
.doc-header h1{font-size:24px;line-height:1.25;margin:0 0 8px}
.back{display:inline-flex;align-items:center;min-height:36px;margin-bottom:8px;color:var(--blue);font-weight:700}
.reader{max-width:900px;margin:0 auto;padding:28px 20px 80px}
.page{background:#fff;border:1px solid var(--line);border-radius:8px;margin:0 0 18px;padding:22px;box-shadow:0 2px 10px rgba(15,23,42,.04)}
.page h2{font-size:15px;color:var(--muted);margin:0 0 14px;border-bottom:1px solid var(--line);padding-bottom:8px}
.page h3{font-size:20px;line-height:1.4;margin:18px 0 8px}
.page p{margin:0 0 12px;text-align:justify}
.page-img{display:block;width:100%;height:auto;border-radius:4px;background:#f1f5f9}
.toc{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px;margin:0 0 18px}
.toc h2{margin:0 0 10px;font-size:16px}.toc a{display:block;color:var(--blue);padding:3px 0}
.empty{color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:8px;padding:24px}
@media(max-width:840px){.shell{display:block}.sidebar{position:static;height:auto}.main{padding:20px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.doc-header{position:static;padding:18px}.reader{padding:18px 12px 56px}.page{padding:14px}}
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
    const okFilter = active === '全部' || card.dataset.category === active || card.dataset.kind === active;
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


def build_doc(pdf: Path) -> DocMeta:
    rel = pdf.relative_to(ROOT)
    title = clean_name(pdf.stem)
    slug = slug_for(pdf)
    doc_dir = PAGE_IMAGES / slug
    doc = fitz.open(pdf)
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        toc = []
    content_parts: list[str] = []
    text_pages = image_pages = chars = 0
    search_chunks: list[str] = []

    if toc:
        toc_links = []
        for level, label, page_no in toc[:120]:
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
                fallback = page.get_text("text") or ""
            except Exception:
                fallback = ""
            blocks = [line.strip() for line in fallback.splitlines() if line.strip()]
        page_text = "\n".join(blocks).strip()
        chars += len(page_text)
        if page_text:
            search_chunks.append(page_text[:1800])
        if len(page_text) >= TEXT_THRESHOLD:
            text_pages += 1
            body = html_page_text(blocks)
        else:
            image_pages += 1
            image_path = doc_dir / f"p{idx:04d}.jpg"
            try:
                render_page(page, image_path)
                rel_img = image_path.relative_to(OUT).as_posix()
                body = (
                    f'<img class="page-img" loading="lazy" '
                    f'src="../{html.escape(rel_img)}" alt="{html.escape(title)} 第 {idx} 页">'
                )
            except Exception as exc:
                body = f'<div class="empty">这一页未能渲染：{html.escape(str(exc))}</div>'
        content_parts.append(f'<section class="page" id="p{idx}"><h2>第 {idx} 页</h2>{body}</section>')

    if not content_parts:
        content_parts.append('<div class="empty">这个 PDF 没有可转换的页面。</div>')

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
    <div class="path">{html.escape(str(rel))}</div>
    <div class="meta">
      <span class="badge">{len(doc)} 页</span>
      <span class="badge text">文字页 {text_pages}</span>
      <span class="badge scan">图像页 {image_pages}</span>
    </div>
  </header>
  <main class="reader">
    {''.join(content_parts)}
  </main>
</body>
</html>
"""
    write_text(DOCS / f"{slug}.html", doc_html)

    search_text = " ".join(search_chunks)
    write_text(DOCS / f"{slug}.search.txt", search_text)
    return DocMeta(
        title=title,
        slug=slug,
        rel_path=str(rel),
        category=category_for(pdf),
        kind=kind_for(pdf),
        pages=len(doc),
        text_pages=text_pages,
        image_pages=image_pages,
        chars=chars,
        href=f"docs/{slug}.html",
    )


def build_index(docs: list[DocMeta]) -> None:
    categories = ["全部"] + sorted({d.category for d in docs}) + sorted({d.kind for d in docs})
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
            cards.append(
                f"""<a class="card" data-card data-category="{html.escape(d.category)}" data-kind="{html.escape(d.kind)}" data-search="{html.escape(search_blob)}" href="{html.escape(d.href)}">
  <h3>{html.escape(d.title)}</h3>
  <div class="path">{html.escape(d.rel_path)}</div>
  <div class="meta">
    <span class="badge">{d.kind}</span>
    <span class="badge">{d.pages} 页</span>
    <span class="badge text">文字 {d.text_pages}</span>
    <span class="badge scan">图像 {d.image_pages}</span>
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
      <p class="sub">PDF 已拆成 HTML 阅读页；扫描件用高分辨率页面图承载，文字层 PDF 直接排成网页文本。</p>
      <input id="search" class="search" type="search" placeholder="搜索标题、年份、类型">
      <div class="filters">{chips}</div>
    </aside>
    <main class="main">
      <section class="stats">
        <div class="stat"><b>{len(docs)}</b><span>PDF 资料</span></div>
        <div class="stat"><b>{sum(d.pages for d in docs)}</b><span>总页数</span></div>
        <div class="stat"><b>{sum(d.text_pages for d in docs)}</b><span>文字页</span></div>
        <div class="stat"><b>{sum(d.image_pages for d in docs)}</b><span>图像页</span></div>
      </section>
      {''.join(sections)}
    </main>
  </div>
  <script>{INDEX_JS}</script>
</body>
</html>
"""
    write_text(OUT / "index.html", index)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    PAGE_IMAGES.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(
        p for p in ROOT.rglob("*.pdf")
        if OUT not in p.parents and ".agents" not in p.parts and ".claude" not in p.parts
    )
    docs = []
    for index, pdf in enumerate(pdfs, start=1):
        print(f"[{index}/{len(pdfs)}] {pdf.relative_to(ROOT)}", flush=True)
        try:
            docs.append(build_doc(pdf))
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
    build_index(docs)
    manifest = [doc.__dict__ for doc in docs]
    write_text(OUT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Built {len(docs)} documents into {OUT}")


if __name__ == "__main__":
    main()
