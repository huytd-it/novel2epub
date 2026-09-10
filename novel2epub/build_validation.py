"""Validate & preview dữ liệu trước khi build EPUB.

Kiểm tra:
- metadata completeness (title/author/description/cover/language)
- chapter-level: encoding, spelling heuristics, strange markers (##, ..., vv)
- link/URL còn sót, han remaining, empty/short, title format, duplicate

Nội dung chương đi qua đúng MỘT bộ luật `CONTENT_CHECKS`, dùng lại ở ba chỗ:
`check_content` (gộp theo chương — trang Build), `validate_chapter_detailed`
(từng vị trí để highlight — trang Chương) và bản mirror client-side
`frontend/src/lib/validation.ts` (check live lúc đang sửa). Thêm/sửa luật thì
sửa `CONTENT_CHECKS` và mirror sang file TS, đừng viết check rời.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import Storage
from .toc import count_words, title_format_ok

# ── Regex patterns cho validation ──────────────────────────────────────────

# Dấu lạ trong bản dịch
RE_HASH_HEADING = re.compile(r"(?:^|\n)\s*#{1,6}\s+", re.MULTILINE)
# code fence markdown còn sót
RE_CODE_FENCE = re.compile(r"```")
# Dấu chấm lạ: 2+ dấu chấm liên tiếp nhưng không phải "..." chuẩn Việt (1 space trước/sau)
# Ta flag các dạng: ".." , "...." , " . . .", "…", mixed
RE_WEIRD_DOTS = re.compile(r"(?:\.{2,}|…{1,}|·{2,}|。{2,})")
# Dấu câu lặp cần dọn: ,, ;; :: --
# Lặp ! và ? là cách nhấn mạnh thường dùng trong hội thoại (!!!, ???).
RE_REPEATED_PUNCT = re.compile(r"([;,:\-–—])\1{1,}")
# Control chars không in được (ngoại trừ \n, \t)
RE_CONTROL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
# Replacement char �
RE_REPLACEMENT = re.compile(r"�")
# Surrogate / isolated? already �
# Mojibake heuristic: sequence like Ã, Â followed by latin extended
RE_MOJIBAKE = re.compile(r"[ÃÂ][\x80-\xBF]{1,2}")
# Mixed zero-width
RE_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")
# Link/URL còn sót: watermark, quảng cáo, "đọc tiếp tại …" của trang nguồn.
# Nhánh 1 bắt link có scheme/`www.`; nhánh 2 bắt tên miền trần (truyenfull.vn)
# với TLD phổ biến, chặn hai đầu bằng lớp ký tự Latin mở rộng để không cắn vào
# chữ tiếng Việt có dấu ("chào.vnghe" không phải link).
RE_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'()\[\]]+"
    r"|(?<![A-Za-zÀ-ỹ0-9@._-])[A-Za-zÀ-ỹ0-9-]+(?:\.[A-Za-zÀ-ỹ0-9-]+)*"
    r"\.(?:com|net|org|vn|info|xyz|top|club|site|online|io|biz|tv)"
    r"(?![A-Za-zÀ-ỹ0-9-])(?:/[^\s<>\"'()\[\]]*)?",
    re.IGNORECASE,
)
# Chữ Hán còn sót (CJK) — bản đếm từng ký tự cho stats
RE_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002EBEF]")
# … và bản gom cụm liên tiếp để highlight (1 issue cho cả cụm, không phải mỗi ký tự)
RE_HAN_CLUSTER = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0002EBEF]+")
# Double spaces (không count dòng trống)
RE_DOUBLE_SPACE = re.compile(r"  +")
# Space trước dấu câu .,!?;:)
RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+[,.!?;:)]")
# Thiếu space sau dấu câu ,.!?;: khi tiếp chữ (ví dụ "xin chào,bạn")
RE_MISSING_SPACE_AFTER = re.compile(r"[,.!?;:][^\s\d\W]")
# Từ lặp liên tiếp — chỉ chữ cái (không \w) để khớp `\p{L}` phía client và
# tránh dính số/underscore
RE_REPEATED_WORD = re.compile(
    r"(?<![^\W\d_])([^\W\d_]+)\s+\1(?![^\W\d_])", re.IGNORECASE | re.UNICODE
)
# Trailing spaces cuối dòng
RE_TRAILING_SPACE = re.compile(r" +$")

# Metadata thresholds
MIN_DESCRIPTION_LEN = 20
MIN_CHAPTER_WORDS = 30  # dưới ngưỡng coi là quá ngắn
SHORT_CHAPTER_WORDS = 100

# Number of preview chapters to include in detail
PREVIEW_CHAPTER_LIMIT = 20
ISSUE_SAMPLE_LIMIT = 30
DETAILED_ISSUE_LIMIT = 120


# ── Bộ kiểm tra nội dung dùng chung ────────────────────────────────────────
# MỘT nguồn sự thật cho hai chỗ hiển thị lỗi: trang Chương (highlight từng vị
# trí qua `validate_chapter_detailed`) và trang Build (gộp theo chương qua
# `check_content`). Cùng regex, cùng level, cùng ngưỡng nên số liệu hai trang
# không lệch nhau. `frontend/src/lib/validation.ts` mirror y hệt danh sách này
# để bản check chạy live lúc đang sửa cũng ra cùng kết quả — sửa ở đây thì sửa
# luôn ở đó.


@dataclass(frozen=True)
class ContentCheck:
    code: str
    level: str  # error | warning | info
    pattern: re.Pattern[str]
    label: str  # message ngắn khi highlight từng vị trí
    hint: str
    summary: str  # message gộp cho trang Build, `{n}` là số chỗ khớp
    # Số match tối thiểu TRONG MỘT ĐOẠN mới coi là lỗi (từ láy tiếng Việt hay
    # lặp hợp lệ nên chỉ báo khi bất thường).
    min_hits: int = 1
    # Các match đúng chuẩn, bỏ qua ("..." và "…" là dấu lửng hợp lệ).
    ignore: tuple[str, ...] = ()


CONTENT_CHECKS: tuple[ContentCheck, ...] = (
    ContentCheck(
        "hash_heading", "warning", RE_HASH_HEADING,
        "Dòng bắt đầu bằng ##", "Tiêu đề không nên có ##",
        "Còn {n} dòng bắt đầu bằng ##/# (markdown heading sót)",
    ),
    ContentCheck(
        "code_fence", "warning", RE_CODE_FENCE,
        "Chứa ```", "Xóa khối code",
        "Có {n} lần ``` (code fence markdown)",
    ),
    ContentCheck(
        "weird_dots", "warning", RE_WEIRD_DOTS,
        "Dấu chấm lạ", "Chuẩn hóa về … hoặc ...",
        "Có {n} cụm dấu chấm lạ (.., ...., ……)",
        ignore=("...", "…"),
    ),
    ContentCheck(
        "repeated_punct", "warning", RE_REPEATED_PUNCT,
        "Dấu câu lặp", "Gộp về 1 dấu",
        "Có {n} cụm dấu câu lặp (,, ;; :: --)",
    ),
    ContentCheck(
        "control_char", "error", RE_CONTROL,
        "Ký tự điều khiển", "Có thể do copy từ web; xóa ký tự \\x00-\\x1F",
        "Chứa {n} ký tự điều khiển vô hình",
    ),
    ContentCheck(
        "replacement_char", "error", RE_REPLACEMENT,
        "Ký tự �", "Crawl sai encoding; kiểm tra source preset rồi crawl lại",
        "Chứa {n} ký tự � (lỗi mã hóa/giải mã)",
    ),
    ContentCheck(
        "mojibake", "warning", RE_MOJIBAKE,
        "Mojibake", "Có thể double-decode UTF-8; kiểm tra source encoding",
        "Nghi ngờ mojibake ở {n} chỗ (ÃÂ…)",
    ),
    ContentCheck(
        "zero_width", "warning", RE_ZERO_WIDTH,
        "Zero-width", "Vô hình nhưng làm sai tìm kiếm; nên xóa",
        "Chứa {n} ký tự zero-width (\\u200B/\\uFEFF)",
    ),
    ContentCheck(
        "url", "warning", RE_URL,
        "Link/URL còn sót", "Watermark hoặc quảng cáo của trang nguồn — xóa hoặc thêm vào strip_patterns",
        "Còn {n} link/URL trong bản dịch (watermark, quảng cáo nguồn)",
    ),
    ContentCheck(
        "han_remaining", "warning", RE_HAN_CLUSTER,
        "Chữ Hán còn sót", "Dùng 'Dọn chữ Hán' hoặc dịch lại",
        "Còn {n} cụm chữ Hán trong bản dịch",
    ),
    ContentCheck(
        "double_space", "info", RE_DOUBLE_SPACE,
        "Double-space", "Thừa khoảng trắng",
        "Có {n} chỗ double-space",
    ),
    ContentCheck(
        "space_before_punct", "info", RE_SPACE_BEFORE_PUNCT,
        "Thừa space trước dấu câu", "Ví dụ 'xin chào ,' → 'xin chào,'",
        "Có {n} chỗ thừa space trước dấu câu",
    ),
    ContentCheck(
        "trailing_space", "info", RE_TRAILING_SPACE,
        "Thừa space cuối dòng", "Không ảnh hưởng EPUB nhưng nên dọn",
        "Có {n} dòng thừa space cuối dòng",
    ),
    ContentCheck(
        "missing_space_after", "info", RE_MISSING_SPACE_AFTER,
        "Thiếu space sau dấu câu", "Ví dụ 'xin chào,bạn' → 'xin chào, bạn'",
        "Có {n} chỗ thiếu space sau dấu câu",
    ),
    ContentCheck(
        "repeated_word", "info", RE_REPEATED_WORD,
        "Từ lặp liên tiếp", "Tiếng Việt có từ láy (từ từ, xa xa) — chỉ báo khi >3 chỗ trong cùng đoạn",
        "Có {n} cụm từ lặp liên tiếp",
        min_hits=4,
    ),
)


def scan_content(text: str) -> tuple[list[str], list[tuple[ContentCheck, int, re.Match[str]]]]:
    """Quét nội dung theo đoạn, trả `(paras, hits)` với hit = (check, para_index, match).

    Tách đoạn đúng bằng `notes.split_paras` (mỗi dòng non-empty = 1 đoạn) nên
    `para_index` khớp với danh sách đoạn reader đang hiển thị.
    """
    from .notes import split_paras

    if not text or not text.strip():
        return [], []
    paras = split_paras(text)
    hits: list[tuple[ContentCheck, int, re.Match[str]]] = []
    for para_index, para in enumerate(paras):
        url_spans = [m.span() for m in RE_URL.finditer(para)]
        for check in CONTENT_CHECKS:
            matches = [m for m in check.pattern.finditer(para) if m.group(0) not in check.ignore]
            if check.code != "url":
                # Dấu chấm/space bên trong link không phải lỗi chính tả —
                # bản thân cái link đã được báo bằng mã `url`.
                matches = [
                    m for m in matches
                    if not any(s <= m.start() and m.end() <= e for s, e in url_spans)
                ]
            if len(matches) < check.min_hits:
                continue
            hits.extend((check, para_index, m) for m in matches)
    return paras, hits


def check_content(text: str) -> list[dict[str, str]]:
    """Bản gộp theo chương cho trang Build — cùng luật với bản highlight per-para."""
    _paras, hits = scan_content(text)
    counts: dict[str, int] = {}
    for check, _para_index, _match in hits:
        counts[check.code] = counts.get(check.code, 0) + 1
    return [
        {
            "code": check.code,
            "level": check.level,
            "message": check.summary.format(n=counts[check.code]),
            "hint": check.hint,
        }
        for check in CONTENT_CHECKS
        if counts.get(check.code)
    ]


def validate_metadata(cfg, manifest) -> list[dict[str, Any]]:
    """Check novel metadata completeness."""
    out: list[dict[str, Any]] = []
    novel = cfg.novel
    if not (novel.title or "").strip():
        out.append({"code": "missing_title", "level": "error", "field": "title", "message": "Thiếu tiêu đề sách", "hint": "Điền ở Cài đặt → Thông tin truyện"})
    if not (novel.author or "").strip():
        out.append({"code": "missing_author", "level": "warning", "field": "author", "message": "Thiếu tác giả", "hint": "EPUB sẽ không có author"})
    if not (novel.description or "").strip():
        out.append({"code": "missing_description", "level": "warning", "field": "description", "message": "Thiếu mô tả", "hint": "Mô tả giúp phân biệt sách trong thư viện"})
    elif len((novel.description or "").strip()) < MIN_DESCRIPTION_LEN:
        out.append({"code": "short_description", "level": "info", "field": "description", "message": f"Mô tả quá ngắn ({len(novel.description.strip())} ký tự)", "hint": "Nên ≥ 20 ký tự"})
    if not cfg.novel.language:
        out.append({"code": "missing_language", "level": "info", "field": "language", "message": "Thiếu ngôn ngữ (mặc định vi)", "hint": ""})
    # cover
    has_cover = bool(manifest and manifest.cover_file) or bool(novel.cover_url)
    if not has_cover:
        out.append({"code": "missing_cover", "level": "info", "field": "cover", "message": "Chưa có ảnh bìa", "hint": "EPUB sẽ không có cover"})
    # toc_url
    if not cfg.crawl.toc_url:
        out.append({"code": "missing_toc_url", "level": "error", "field": "toc_url", "message": "Thiếu URL mục lục", "hint": ""})
    return out


def validate_chapter(ch, storage: Storage, publication_text: str | None = None) -> dict[str, Any]:
    """Validate 1 chương, trả {index, title, issues: [...], stats}."""
    title = storage.publication_title(ch) if hasattr(storage, "publication_title") else ch.title
    # Resolve text to validate: prefer publication_text (what goes into EPUB)
    text = publication_text if publication_text is not None else ""
    # If publication_text not provided, try to resolve
    if publication_text is None:
        try:
            pv = storage.publication_version(ch)
            text = pv.text if pv else ""
            title = pv.title if pv and pv.title else ch.title
        except Exception:
            text = ""

    issues: list[dict[str, Any]] = []

    # title format
    if ch.skipped:
        issues.append({"code": "skipped", "level": "info", "message": "Chương bị bỏ qua (skipped)", "hint": "Không vào EPUB"})
    else:
        if not title or not title.strip():
            issues.append({"code": "missing_title", "level": "error", "message": "Thiếu tiêu đề", "hint": "Dùng 'Chuẩn hóa TOC'"})
        elif not title_format_ok(title):
            issues.append({"code": "title_format", "level": "warning", "message": f"Tiêu đề sai mẫu: {title[:60]!r}", "hint": "Mẫu đúng: 'Chương N: Tên chương' và không còn chữ Hán"})
        # duplicate
        if getattr(ch, "duplicate_of", None) is not None:
            issues.append({"code": "duplicate", "level": "warning", "message": f"Trùng với chương {ch.duplicate_of}", "hint": "Cùng URL+tiêu đề"})

        # publishing readiness
        if publication_text is None:
            pv = storage.publication_version(ch)
            if pv is None:
                issues.append({"code": "not_ready", "level": "error", "message": "Chưa có bản AI hoặc Local MT hoàn chỉnh", "hint": "Dịch chương trước khi build"})
                # no text to check further
                return {"index": ch.index, "title": title, "issues": issues, "word_count": 0, "char_count": 0, "han_count": 0}

        # empty/short
        if not text or not text.strip():
            issues.append({"code": "empty_content", "level": "error", "message": "Nội dung rỗng", "hint": "Crawl/dịch lại"})
        else:
            wc = count_words(text)
            if wc < MIN_CHAPTER_WORDS:
                issues.append({"code": "too_short", "level": "warning", "message": f"Quá ngắn ({wc} từ)", "hint": "Có thể crawl lỗi hoặc chưa dịch xong"})
            elif wc < SHORT_CHAPTER_WORDS:
                issues.append({"code": "short", "level": "info", "message": f"Ngắn ({wc} từ)", "hint": ""})

            # Cùng bộ luật với trang Chương, chỉ khác là gộp theo mã lỗi
            issues.extend(check_content(text))

    # stats
    wc = count_words(text) if text else 0
    return {
        "index": ch.index,
        "title": title,
        "skipped": bool(ch.skipped),
        "issues": issues,
        "word_count": wc,
        "char_count": len(text) if text else 0,
        "han_count": len(RE_HAN.findall(text)) if text else 0,
    }


def validate_chapter_detailed(text: str, title: str = "") -> dict[str, Any]:
    """Chi tiết per-para với vị trí highlight — dùng cho tab Lỗi trong ChapterPage.

    Trả {issues: [{code, level, message, hint, paraIndex, start, end, snippet}], summary, perPara}
    ParaIndex theo notes.split_paras (mỗi dòng non-empty = 1 para). Issues có paraIndex=-1 là lỗi tiêu đề/toàn chương.
    Cùng `CONTENT_CHECKS` với `check_content` nên trang Chương và trang Build
    báo đúng một tập lỗi, chỉ khác cách trình bày (từng vị trí vs. gộp số lượng).
    """
    issues: list[dict[str, Any]] = []

    # title
    if title is not None:
        if not (title or "").strip():
            issues.append({"code": "missing_title", "level": "error", "message": "Thiếu tiêu đề", "hint": "Dùng 'Chuẩn hóa TOC'", "paraIndex": -1, "start": 0, "end": 0, "snippet": ""})
        elif not title_format_ok(title):
            issues.append({"code": "title_format", "level": "warning", "message": f"Tiêu đề sai mẫu: {title[:60]!r}", "hint": "Mẫu đúng: 'Chương N: Tên chương'", "paraIndex": -1, "start": 0, "end": len(title), "snippet": title[:60]})

    if not text or not text.strip():
        if text is not None and not text.strip():
            issues.append({"code": "empty_content", "level": "error", "message": "Nội dung rỗng", "hint": "Crawl/dịch lại", "paraIndex": -1, "start": 0, "end": 0, "snippet": ""})
        summary = {"error": sum(1 for i in issues if i["level"] == "error"), "warning": sum(1 for i in issues if i["level"] == "warning"), "info": sum(1 for i in issues if i["level"] == "info"), "total": len(issues)}
        return {"issues": issues, "summary": summary, "perPara": {}, "title": title}

    paras, hits = scan_content(text)
    for check, para_index, match in hits:
        para = paras[para_index]
        start, end = match.span()
        issues.append({
            "code": check.code,
            "level": check.level,
            "message": check.label,
            "hint": check.hint,
            "paraIndex": para_index,
            "start": start,
            "end": end,
            "snippet": para[max(0, start - 12): min(len(para), end + 12)].strip(),
        })
    # limit total
    if len(issues) > DETAILED_ISSUE_LIMIT:
        issues = issues[:DETAILED_ISSUE_LIMIT]

    per_para: dict[int, list[dict[str, Any]]] = {}
    for iss in issues:
        per_para.setdefault(iss["paraIndex"], []).append(iss)

    summary = {"error": sum(1 for i in issues if i["level"] == "error"), "warning": sum(1 for i in issues if i["level"] == "warning"), "info": sum(1 for i in issues if i["level"] == "info"), "total": len(issues)}
    return {"issues": issues, "summary": summary, "perPara": per_para, "title": title, "paraCount": len(paras)}


def build_preview_payload(cfg, storage: Storage, *, sample_limit: int = 12) -> dict[str, Any]:
    """Build toàn bộ payload cho trang Build: stats + metadata + validation + preview.

    Không gọi model, chỉ đọc DB/manifest.
    """
    from pathlib import Path

    manifest = storage.load_manifest()
    if manifest is None:
        return {
            "has_manifest": False,
            "total": 0,
            "skipped": 0,
            "ready": 0,
            "blocked": 0,
            "metadata": validate_metadata(cfg, None),
            "stats": {
                "total": 0, "skipped": 0, "ready": 0, "blocked": 0,
                "word_count": 0, "char_count": 0, "avg_words": 0,
                "han_total": 0, "branches": {},
                "chapters_with_issues": 0,
            },
            "validation": {
                "summary": {"error": 0, "warning": 0, "info": 0, "total_issues": 0},
                "groups": [],
                "chapters": [],
            },
            "preview": {
                "chapters": [], "cover": None, "epub": {"exists": False, "path": cfg.epub_path, "size": 0, "stale": False},
                "will_include": 0, "will_exclude": 0,
            },
            "blockers": [],
            "can_build": False,
        }

    chapters = manifest.chapters
    total = len(chapters)
    skipped = sum(1 for ch in chapters if ch.skipped)

    # Branch counts
    from novel2epub import revisions as _rev
    branches: dict[str, dict] = {}
    for b in _rev.BRANCHES:
        cnt = sum(1 for ch in chapters if storage.has_branch_text(ch, b))
        branches[b] = {"count": cnt, "label": _rev.branch_label(b)}

    # Build blockers (what stops strict build)
    blockers = storage.build_blockers(chapters)
    blocked = len(blockers)
    ready = total - skipped - blocked

    # Metadata validation
    meta_issues = validate_metadata(cfg, manifest)

    # Per-chapter validation
    chapter_reports: list[dict[str, Any]] = []
    word_total = 0
    char_total = 0
    han_total = 0
    # aggregate groups
    group_counts: dict[str, dict[str, int]] = {}
    # level summary
    level_summary = {"error": 0, "warning": 0, "info": 0}

    # For preview: collect will_include chapters (publication_version != None)
    preview_chapters: list[dict[str, Any]] = []
    will_include = 0
    will_exclude = 0

    for ch in chapters:
        # Use publication_version to get text that will be in EPUB
        pv = storage.publication_version(ch)
        text = pv.text if pv else ""
        report = validate_chapter(ch, storage, publication_text=text if not ch.skipped and pv else ("" if ch.skipped else None))
        # If skipped, we already have issues but don't count towards word totals?
        # For skipped, publication_text is empty on purpose
        if pv is not None:
            word_total += report["word_count"]
            char_total += report["char_count"]
            han_total += report["han_count"]
            will_include += 1
            # preview sample
            if len(preview_chapters) < PREVIEW_CHAPTER_LIMIT:
                # snippet: first 200 chars
                snippet = (text[:220].replace("\n", " ").strip() + ("…" if len(text) > 220 else "")) if text else ""
                preview_chapters.append({
                    "index": ch.index,
                    "title": report["title"],
                    "word_count": report["word_count"],
                    "char_count": report["char_count"],
                    "branch": pv.branch,
                    "snippet": snippet,
                    "issues": [i for i in report["issues"] if i["level"] in ("error", "warning")][:2],  # top 2
                })
        else:
            will_exclude += 1

        # aggregate issues
        for iss in report["issues"]:
            lvl = iss.get("level", "info")
            if lvl in level_summary:
                level_summary[lvl] += 1
            code = iss.get("code", "unknown")
            grp = group_counts.setdefault(code, {"code": code, "level": lvl, "count": 0, "examples": [], "message": iss.get("message", "")})
            grp["count"] += 1
            # Keep message of first occurrence
            if len(grp["examples"]) < 3:
                grp["examples"].append({"index": ch.index, "title": report["title"][:60]})
            # propagate highest level
            # error > warning > info
            order = {"error": 3, "warning": 2, "info": 1}
            if order.get(lvl, 0) > order.get(grp["level"], 0):
                grp["level"] = lvl
                grp["message"] = iss.get("message", "")

        # keep per-chapter if has issues beyond 'skipped' info? Keep all with error/warning
        has_significant = any(i["level"] in ("error", "warning") for i in report["issues"])
        if has_significant:
            # limit issues per chapter to 6 for payload size
            report["issues"] = report["issues"][:6]
            chapter_reports.append(report)
        elif report["issues"]:
            # keep info-only chapters only if not too many
            if len(chapter_reports) < 50:
                report["issues"] = report["issues"][:3]
                chapter_reports.append(report)

        # cap chapter_reports
        if len(chapter_reports) >= 80:
            # stop collecting detailed per-chapter, but continue counting groups
            pass

    # sort groups by severity then count
    groups = sorted(group_counts.values(), key=lambda g: (-{"error": 3, "warning": 2, "info": 1}[g["level"]], -g["count"]))

    # stats
    avg_words = round(word_total / max(will_include, 1)) if will_include else 0
    stats = {
        "total": total,
        "skipped": skipped,
        "ready": ready,
        "blocked": blocked,
        "will_include": will_include,
        "will_exclude": will_exclude,
        "word_count": word_total,
        "char_count": char_total,
        "avg_words": avg_words,
        "han_total": han_total,
        "branches": branches,
        "chapters_with_issues": len([r for r in chapter_reports if any(i["level"] in ("error", "warning") for i in r["issues"])]),
    }

    # epub artifact
    epub_path = Path(cfg.epub_path)
    epub_exists = epub_path.exists()
    build = storage.read_build()
    stale = storage.build_stale()
    preview = {
        "chapters": preview_chapters,
        "total_preview": len(preview_chapters),
        "total_will_include": will_include,
        "cover": {
            "has_cover": bool(manifest.cover_file or cfg.novel.cover_url),
            "cover_file": manifest.cover_file or "",
            "cover_url": cfg.novel.cover_url or "",
        },
        "epub": {
            "exists": epub_exists,
            "path": str(epub_path),
            "size": epub_path.stat().st_size if epub_exists else 0,
            "stale": stale,
            "build": build,
        },
        "will_include": will_include,
        "will_exclude": will_exclude,
        "toc_url": cfg.crawl.toc_url,
        "language": cfg.novel.language,
        "title": cfg.novel.title or manifest.title or manifest.slug,
        "author": cfg.novel.author or manifest.author or "",
        "publisher": cfg.novel.publisher or "",
    }

    # can_build strictly requires no blockers and no metadata error blocking?
    # Metadata error (missing_title/toc_url) also blocks
    meta_errors = [m for m in meta_issues if m["level"] == "error"]
    can_build = blocked == 0 and not meta_errors and will_include > 0

    # Blockers detail for UI
    blocker_details = storage.build_blockers(chapters) if blocked else []

    # Truncate chapter_reports if too large
    if len(chapter_reports) > 60:
        chapter_reports = chapter_reports[:60]

    return {
        "has_manifest": True,
        "total": total,
        "skipped": skipped,
        "ready": ready,
        "blocked": blocked,
        "metadata": meta_issues,
        "stats": stats,
        "validation": {
            "summary": {"error": level_summary["error"], "warning": level_summary["warning"], "info": level_summary["info"], "total_issues": sum(level_summary.values())},
            "groups": groups,
            "chapters": chapter_reports,
        },
        "preview": preview,
        "blockers": blocker_details,
        "can_build": can_build,
    }
