"""Dữ liệu tổng quan cho NHIỀU ebook cùng lúc (Thư viện, Dashboard).

Các màn hình liệt kê trước đây dựng `Manifest` cho từng ebook chỉ để đếm chương
và vẽ dải tiến độ — mỗi lần là một lượt quét bảng `chapters` (bảng giữ blob
raw/dịch, hàng GB). Ở đây gom cả danh sách lại thành một số query cố định trên
projection hẹp `chapter_ui_state`.
"""
from __future__ import annotations

from collections.abc import Sequence

from novel2epub.storage import bulk_chapter_states


def chapter_states_by_slug(pairs: Sequence[tuple[str, object]]) -> dict[str, list[dict]]:
    """`{slug: [trạng thái từng chương]}` cho danh sách `(slug, cfg)`.

    Gom theo `cfg.output.data_dir`: mỗi DB chỉ tốn đúng một lượt truy vấn. Không
    giả định cả danh sách nằm chung một file `.db` — test (và cấu hình nhiều
    workspace) có thể trỏ mỗi ebook sang một DB riêng.
    """
    by_dir: dict[str, list[str]] = {}
    for _slug, cfg in pairs:
        by_dir.setdefault(str(cfg.output.data_dir), []).append(cfg.novel.slug)
    states = {
        data_dir: bulk_chapter_states(data_dir, slugs)
        for data_dir, slugs in by_dir.items()
    }
    return {
        slug: states[str(cfg.output.data_dir)].get(cfg.novel.slug, [])
        for slug, cfg in pairs
    }
