"""Nhãn hiển thị thống nhất cho job queue.

`step`, category, UUID và slug là định danh kỹ thuật; các helper ở đây chỉ tạo
`label` cho người dùng theo mẫu ``Hành động · Tên truyện · Chi tiết``.
"""
from __future__ import annotations

from collections.abc import Sequence


ACTION_LABELS = {
    "ai-review": "AI rà soát",
    "ai-rewrite": "AI biên tập",
    "ai-suggest": "AI gợi ý thuật ngữ",
    "automation": "Tự động hóa",
    "build": "Đóng gói EPUB",
    "build-selected": "Đóng gói EPUB",
    "chapter-cleanup-han": "Dọn chữ Hán",
    "chapter-crawl": "Cào chương",
    "chapter-translate": "Dịch chương",
    "cleanup-han": "Dọn chữ Hán",
    "cleanup-han-local-mt": "Dọn chữ Hán bằng Local MT",
    "crawl": "Cào dữ liệu",
    "delete-translation": "Xóa bản dịch",
    "fetch-toc": "Cập nhật mục lục",
    "glossary-approve": "Duyệt thuật ngữ",
    "local-mt": "Dịch Local MT",
    "opds-autobuild": "Tự động đóng gói EPUB",
    "propagate": "Thay thế hàng loạt",
    "publish-reader": "Đăng Reader",
    "reindex": "Lập chỉ mục lại",
    "reorder": "Sắp xếp chương",
    "run": "Chạy toàn bộ",
    "translate": "Dịch",
    "translate-titles": "Dịch tiêu đề",
    "translate-toc-selected": "Dịch tiêu đề",
}

AUTOMATION_STEP_LABELS = {
    "fetch-toc": "Cập nhật mục lục",
    "crawl-new": "Cào chương mới",
    "translate-local-mt": "Dịch Local MT",
    "translate-pending": "LLM dịch",
    "llm-edit": "LLM biên tập",
    "cleanup-han": "Dọn chữ Hán",
    "build": "Đóng gói EPUB",
    "publish-reader": "Đăng Reader",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("-", " ").strip().capitalize())


def ebook_title(title: str | None = None, slug: str | None = None) -> str:
    return (title or "").strip() or (slug or "").strip() or "Truyện không tên"


def chapter_detail(index: int, title: str | None = None) -> str:
    clean_title = (title or "").strip()
    return f"{index}.{clean_title}" if clean_title else f"Chương {index}"


def count_detail(count: int, noun: str = "chương") -> str:
    return f"{count} {noun}"


def job_label(
    action: str,
    *,
    title: str | None = None,
    slug: str | None = None,
    detail: str | None = None,
) -> str:
    parts = [action_label(action)]
    if title or slug:
        parts.append(ebook_title(title, slug))
    if detail and detail.strip():
        parts.append(detail.strip())
    return " · ".join(parts)


def chapter_job_label(
    action: str,
    *,
    title: str | None,
    slug: str | None,
    index: int,
    chapter_title: str | None = None,
) -> str:
    return job_label(
        action,
        title=title,
        slug=slug,
        detail=chapter_detail(index, chapter_title),
    )


def batch_job_label(
    action: str,
    *,
    title: str | None,
    slug: str | None,
    count: int,
    noun: str = "chương",
) -> str:
    return job_label(
        action,
        title=title,
        slug=slug,
        detail=count_detail(count, noun),
    )


def automation_job_label(
    *,
    title: str | None,
    slug: str | None,
    steps: Sequence[str],
) -> str:
    detail = " → ".join(AUTOMATION_STEP_LABELS.get(step, step) for step in steps)
    return job_label("automation", title=title, slug=slug, detail=detail or "Không có bước")
