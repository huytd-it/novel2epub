"""Validate & preview dữ liệu trước khi build EPUB.

Kiểm tra:
- metadata completeness (title/author/description/cover/language)
- chapter-level: encoding, spelling heuristics, strange markers (##, ..., vv)
- han remaining, empty/short, title format, duplicate
Output dùng cho trang Build mới: preview + stats + validation groups.
"""
from __future__ import annotations

import re
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
# Dấu câu lặp: !! ?? ,, ;; :: --
RE_REPEATED_PUNCT = re.compile(r"([!?;,:\-–—])\1{1,}")
# Control chars không in được (ngoại trừ \n, \t)
RE_CONTROL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
# Replacement char �
RE_REPLACEMENT = re.compile(r"\uFFFD")
# Surrogate / isolated? already �
# Mojibake heuristic: sequence like Ã, Â followed by latin extended
RE_MOJIBAKE = re.compile(r"[ÃÂ][\x80-\xBF]{1,2}")
# Mixed zero-width
RE_ZERO_WIDTH = re.compile(r"[\u200B\u200C\u200D\uFEFF]")
# Chữ Hán còn sót (CJK)
RE_HAN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002EBEF]")
# Double spaces (không count dòng trống)
RE_DOUBLE_SPACE = re.compile(r"  +")
# Space trước dấu câu .,!?;:)
RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+[,.!?;:)]")
# Thiếu space sau dấu câu ,.!?;: khi tiếp chữ (ví dụ "xin chào,bạn")
RE_MISSING_SPACE_AFTER = re.compile(r"[,.!?;:][^\s\d\W]")
# Repeated words (word lặp liên tiếp)
RE_REPEATED_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE | re.UNICODE)
# Trailing spaces per line
RE_TRAILING_SPACE = re.compile(r" +\n")
# Too many blank lines (3+ liên tiếp)
RE_MANY_BLANKS = re.compile(r"\n{3,}")


# Spelling: heuristic set - từ lặp, double space đã cover. Thêm:
# - chữ thường sau dấu chấm không cách? already flagged.
# - viết hoa bất thường giữa câu? not critical, flag.
RE_MID_SENTENCE_CAPS = re.compile(r"(?<=[a-zà-ỹ]\s)[A-ZÀ-Ỹ]{2,}")

# Metadata thresholds
MIN_DESCRIPTION_LEN = 20
MIN_CHAPTER_WORDS = 30  # dưới ngưỡng coi là quá ngắn
SHORT_CHAPTER_WORDS = 100

HAN_THRESHOLD = 5  # >5 chữ Hán trong bản dịch → warning

# Number of preview chapters to include in detail
PREVIEW_CHAPTER_LIMIT = 20
ISSUE_SAMPLE_LIMIT = 30


def _check_encoding(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not text:
        return issues
    if RE_REPLACEMENT.search(text):
        issues.append({"code": "replacement_char", "level": "error", "message": "Chứa ký tự � (lỗi mã hóa/giải mã)", "hint": "Bản gốc có thể bị crawl sai encoding; thử crawl lại hoặc kiểm tra source preset encoding"})
    if RE_CONTROL.search(text):
        issues.append({"code": "control_char", "level": "error", "message": "Chứa ký tự điều khiển vô hình", "hint": "Có thể do copy từ web; xóa ký tự \\x00-\\x1F"})
    if RE_ZERO_WIDTH.search(text):
        issues.append({"code": "zero_width", "level": "warning", "message": "Chứa ký tự zero-width (\\u200B/\\uFEFF)", "hint": "Vô hình nhưng làm sai tìm kiếm; nên xóa"})
    if RE_MOJIBAKE.search(text):
        issues.append({"code": "mojibake", "level": "warning", "message": "Nghi ngờ mojibake (ÃÂ…)", "hint": "Có thể double-decode UTF-8; kiểm tra source encoding"})
    return issues


def _check_strange_markers(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not text:
        return issues
    if RE_HASH_HEADING.search(text):
        # count occurrences
        cnt = len(RE_HASH_HEADING.findall(text))
        issues.append({"code": "hash_heading", "level": "warning", "message": f"Còn {cnt} dòng bắt đầu bằng ##/# (markdown heading sót)", "hint": "Tiêu đề chương không nên có ##; đã được chuẩn hóa trong pipeline nhưng bản dịch có thể còn"})
    if RE_CODE_FENCE.search(text):
        issues.append({"code": "code_fence", "level": "warning", "message": "Chứa ``` (code fence markdown)", "hint": "Không nên có trong truyện; xóa khối code"})
    # weird dots: chỉ flag ".." (2 chấm) và "...." (4+) — cho phép "..." và "…" đơn là chuẩn
    dots = RE_WEIRD_DOTS.findall(text)
    weird = [d for d in dots if d not in ("...", "…")]
    if weird:
        issues.append({"code": "weird_dots", "level": "warning", "message": f"Có {len(weird)} cụm dấu chấm lạ (.., ...., ……)", "hint": "Chuẩn hóa về … hoặc ..."})
    elif len(dots) > 30:
        issues.append({"code": "weird_dots", "level": "info", "message": f"Có {len(dots)} lần '...' / '…' (nhiều)", "hint": "Nhiều dấu lửng, kiểm tra lạm dụng"})
    if RE_REPEATED_PUNCT.search(text):
        cnt = len(RE_REPEATED_PUNCT.findall(text))
        issues.append({"code": "repeated_punct", "level": "warning", "message": f"Có {cnt} cụm dấu câu lặp (!! ?? ,, ;; )", "hint": "Gộp về 1 dấu"})
    if RE_MANY_BLANKS.search(text):
        issues.append({"code": "many_blanks", "level": "info", "message": "Có đoạn trống 3+ dòng liên tiếp", "hint": "EPUB sẽ gộp thành 1 đoạn; không ảnh hưởng nhưng nên dọn"})
    return issues


def _check_spelling(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not text:
        return issues
    # double spaces (không tính đầu dòng indent)
    if RE_DOUBLE_SPACE.search(text):
        cnt = len(RE_DOUBLE_SPACE.findall(text))
        issues.append({"code": "double_space", "level": "info", "message": f"Có {cnt} chỗ double-space", "hint": "Thừa khoảng trắng"})
    if RE_SPACE_BEFORE_PUNCT.search(text):
        cnt = len(RE_SPACE_BEFORE_PUNCT.findall(text))
        issues.append({"code": "space_before_punct", "level": "info", "message": f"Có {cnt} chỗ thừa space trước dấu câu", "hint": "Ví dụ 'xin chào ,' → 'xin chào,'"})
    if RE_MISSING_SPACE_AFTER.search(text):
        cnt = len(RE_MISSING_SPACE_AFTER.findall(text))
        issues.append({"code": "missing_space_after", "level": "info", "message": f"Có {cnt} chỗ thiếu space sau dấu câu", "hint": "Ví dụ 'xin chào,bạn' → 'xin chào, bạn'"})
    if RE_REPEATED_WORD.search(text):
        cnt = len(RE_REPEATED_WORD.findall(text))
        # Tiếng Việt có nhiều từ láy lặp (từ từ, xa xa, nhè nhẹ) nên chỉ cảnh báo khi lặp nhiều bất thường
        if cnt > 3:
            issues.append({"code": "repeated_word", "level": "info", "message": f"Có {cnt} cụm từ lặp liên tiếp", "hint": "Tiếng Việt có từ láy (từ từ, xa xa) — kiểm tra nếu >3 chỗ"})
    if RE_TRAILING_SPACE.search(text + "\n"):
        issues.append({"code": "trailing_space", "level": "info", "message": "Có dòng thừa space cuối dòng", "hint": "Không ảnh hưởng EPUB nhưng nên dọn"})
    return issues


def _check_han(text: str) -> list[dict[str, str]]:
    if not text:
        return []
    cnt = len(RE_HAN.findall(text))
    if cnt >= HAN_THRESHOLD:
        return [{"code": "han_remaining", "level": "warning" if cnt < 50 else "error", "message": f"Còn {cnt} ký tự Hán trong bản dịch", "hint": "Dùng 'Dọn chữ Hán' hoặc dịch lại"}]
    if cnt > 0:
        return [{"code": "han_remaining", "level": "info", "message": f"Còn {cnt} ký tự Hán", "hint": "Ít, có thể là thuật ngữ giữ lại"}]
    return []


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

            # run sub-checks
            for grp in (_check_encoding(text), _check_strange_markers(text), _check_spelling(text), _check_han(text)):
                for it in grp:
                    # attach location hint: chapter index
                    issues.append(it)

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
    """
    from .notes import split_paras

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

    paras = split_paras(text)

    # helpers to push per-para matches
    def _push_matches(pattern: re.Pattern, code: str, level: str, message: str, hint: str = ""):
        for para_idx, para in enumerate(paras):
            # cần clone pattern vì flag g
            for m in re.finditer(pattern, para):
                s, e = m.start(), m.end()
                # filter weird_dots: bỏ "..." và "…" chuẩn
                if code == "weird_dots" and m.group(0) in ("...", "…"):
                    continue
                snippet = para[max(0, s - 12): min(len(para), e + 12)].strip()
                issues.append({"code": code, "level": level, "message": message, "hint": hint, "paraIndex": para_idx, "start": s, "end": e, "snippet": snippet})

    _push_matches(RE_HASH_HEADING, "hash_heading", "warning", "Dòng bắt đầu bằng ##", "Tiêu đề không nên có ##")
    _push_matches(RE_CODE_FENCE, "code_fence", "warning", "Chứa ```", "Xóa khối code")
    # weird_dots: dùng pattern gốc, sẽ filter trong _push
    for para_idx, para in enumerate(paras):
        dots = RE_WEIRD_DOTS.findall(para)
        weird = [d for d in dots if d not in ("...", "…")]
        if weird:
            for m in re.finditer(RE_WEIRD_DOTS, para):
                if m.group(0) in ("...", "…"):
                    continue
                s, e = m.start(), m.end()
                snippet = para[max(0, s - 12): min(len(para), e + 12)].strip()
                issues.append({"code": "weird_dots", "level": "warning", "message": "Dấu chấm lạ", "hint": "Chuẩn hóa về …", "paraIndex": para_idx, "start": s, "end": e, "snippet": snippet})

    _push_matches(RE_REPEATED_PUNCT, "repeated_punct", "warning", "Dấu câu lặp", "Gộp về 1 dấu")
    _push_matches(RE_CONTROL, "control_char", "error", "Ký tự điều khiển", "")
    _push_matches(RE_REPLACEMENT, "replacement_char", "error", "Ký tự �", "Lỗi mã hóa")
    _push_matches(RE_MOJIBAKE, "mojibake", "warning", "Mojibake", "")
    _push_matches(RE_ZERO_WIDTH, "zero_width", "warning", "Zero-width", "")
    # han: highlight từng cụm han liên tiếp — dùng cluster để tránh duplicate
    _HAN_CLUSTER = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002EBEF]+")
    for para_idx, para in enumerate(paras):
        for m in _HAN_CLUSTER.finditer(para):
            s, e = m.start(), m.end()
            snippet = para[max(0, s - 6): min(len(para), e + 6)]
            issues.append({"code": "han_remaining", "level": "warning", "message": "Chữ Hán còn sót", "hint": "Dọn chữ Hán", "paraIndex": para_idx, "start": s, "end": e, "snippet": snippet})
    _push_matches(RE_DOUBLE_SPACE, "double_space", "info", "Double-space", "")
    _push_matches(RE_SPACE_BEFORE_PUNCT, "space_before_punct", "info", "Thừa space trước dấu câu", "")
    _push_matches(RE_TRAILING_SPACE, "trailing_space", "info", "Thừa space cuối dòng", "")
    # missing_space_after: [,.!?;:][^\s\d\W]
    _push_matches(re.compile(r"[,.!?;:][^\s\d\W]"), "missing_space_after", "info", "Thiếu space sau dấu câu", "")
    # repeated_word: only if >3 not handled per para, but we push per occurrence
    for para_idx, para in enumerate(paras):
        for m in re.finditer(RE_REPEATED_WORD, para):
            s, e = m.start(), m.end()
            snippet = para[max(0, s - 10): min(len(para), e + 10)]
            issues.append({"code": "repeated_word", "level": "info", "message": "Từ lặp liên tiếp", "hint": "", "paraIndex": para_idx, "start": s, "end": e, "snippet": snippet})
    # limit total
    if len(issues) > 120:
        issues = issues[:120]

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
