from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "study-html"
DOCS = OUT / "docs"
MANIFEST = OUT / "manifest.json"
QUALITY_REPORT = OUT / "quality-report.json"
IMG_SRC_RE = re.compile(r'src="\.\./([^"]+)"')


@dataclass
class AuditResult:
    documents: int
    pages: int
    text_pages: int
    image_pages: int
    image_refs: int
    missing_images: int
    empty_search_files: int
    suspicious_text_files: int
    quality_report_exists: bool
    quality_page_issues: int


def load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def count_missing_images() -> tuple[int, int]:
    refs = 0
    missing = 0
    for html_file in DOCS.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        for match in IMG_SRC_RE.finditer(content):
            refs += 1
            target = OUT / match.group(1)
            if not target.exists():
                missing += 1
    return refs, missing


def looks_suspicious_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    chinese = len(re.findall(r"[\u4e00-\u9fff]", compact))
    punctuation = len(re.findall(r"[。！？；，、：,.!?;:]", compact))
    return len(compact) < 120 or chinese / len(compact) < 0.25 or punctuation == 0


def count_search_quality() -> tuple[int, int]:
    empty = 0
    suspicious = 0
    for search_file in DOCS.glob("*.search.txt"):
        text = search_file.read_text(encoding="utf-8").strip()
        if not text:
            empty += 1
        elif looks_suspicious_text(text):
            suspicious += 1
    return empty, suspicious


def load_quality_issue_count() -> tuple[bool, int]:
    if not QUALITY_REPORT.exists():
        return False, 0
    data = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
    return True, int(data.get("summary", {}).get("page_issues", 0))


def audit() -> AuditResult:
    manifest = load_manifest()
    image_refs, missing_images = count_missing_images()
    empty_search, suspicious_search = count_search_quality()
    quality_exists, quality_page_issues = load_quality_issue_count()
    return AuditResult(
        documents=len(manifest),
        pages=sum(item.get("pages", 0) for item in manifest),
        text_pages=sum(item.get("text_pages", 0) for item in manifest),
        image_pages=sum(item.get("image_pages", 0) for item in manifest),
        image_refs=image_refs,
        missing_images=missing_images,
        empty_search_files=empty_search,
        suspicious_text_files=suspicious_search,
        quality_report_exists=quality_exists,
        quality_page_issues=quality_page_issues,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit generated study-html output.")
    parser.add_argument("--allow-missing-images", action="store_true", help="Report missing images but do not exit non-zero for them.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = audit()
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    if result.missing_images and not args.allow_missing_images:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
