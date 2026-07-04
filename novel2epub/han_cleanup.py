"""Phát hiện và sửa chữa ký tự Trung Quốc còn sót trong bản dịch.

Luồng xử lý:
1. Quét bản dịch → tìm đoạn chứa ký tự Hán
2. Gom các đoạn có vấn đề, gửi AI với prompt sửa chọn lọc
3. Parse response và thay thế chính xác vào bản dịch gốc
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import openai_client
from .config import OpenAIConfig

_HAN_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")

CLEANUP_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt, chuyên sửa các lỗi sót chữ Hán.

Đoạn văn dưới đây là bản dịch tiếng Việt, NHƯNG còn chứa một số ký tự/ký hiệu Trung Quốc được đánh dấu bằng <HAN>...</HAN>.
NHIỆM VỤ: Chỉ sửa các phần được đánh dấu <HAN>...</HAN> thành tiếng Việt tự nhiên, GIỮ NGUYÊN phần còn lại.

NGUYÊN TẮC:
- Không thay đổi bất kỳ chữ nào ngoài vùng <HAN>...</HAN>.
- Nếu cả câu cần viết lại cho mượt vì vùng <HAN> nằm giữa câu, chỉ sửa vùng đó và tối thiểu từ xung quanh để câu tự nhiên.
- KHÔNG thêm lời mở đầu, giải thích, code fence.
- KHÔNG dùng định dạng song ngữ.

--- Bản đối chiếu gốc (Trung), dùng làm ngữ cảnh ---
{raw_paragraph}

--- Bản dịch cần sửa (vùng Hán đã đánh dấu) ---
{marked_text}

Chỉ trả về toàn bộ đoạn văn đã sửa (giữ nguyên mọi thứ, chỉ thay thế nội dung trong <HAN>...</HAN> bằng tiếng Việt)."""


def find_han_regions(
    translated: str,
    min_context_chars: int = 60,
    max_gap: int = 3,
) -> list[dict]:
    """Quét bản dịch, trả list region chứa ký tự Hán.

    Mỗi region = dict:
      - paragraph_index (int): chỉ số đoạn trong paragraph list
      - start (int): offset bắt đầu trong đoạn
      - end (int): offset kết thúc trong đoạn
      - chinese_text (str): chữ Hán tìm được
      - context_before (str): ~min_context_chars ký tự trước region
      - context_after (str): ~min_context_chars ký tự sau region
      - full_paragraph (str): toàn bộ đoạn văn

    Gom các ký tự Hán cách nhau ≤ max_gap ký tự vào cùng 1 region.
    """
    paragraphs = translated.split("\n")
    regions: list[dict] = []

    for para_idx, para in enumerate(paragraphs):
        if not para.strip():
            continue
        matches = list(_HAN_RE.finditer(para))
        if not matches:
            continue

        merged: list[tuple[int, int]] = []
        for m in matches:
            start, end = m.start(), m.end()
            if merged and start - merged[-1][1] <= max_gap:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))

        for start, end in merged:
            chinese_text = para[start:end]
            ctx_before = para[max(0, start - min_context_chars):start]
            ctx_after = para[end:end + min_context_chars]
            regions.append({
                "paragraph_index": para_idx,
                "start": start,
                "end": end,
                "chinese_text": chinese_text,
                "context_before": ctx_before,
                "context_after": ctx_after,
                "full_paragraph": para,
            })

    return regions


def _mark_region(paragraph: str, region: dict) -> str:
    """Đánh dấu vùng Hán bằng <HAN>...</HAN> trong đoạn văn."""
    start = region["start"]
    end = region["end"]
    return paragraph[:start] + "<HAN>" + paragraph[start:end] + "</HAN>" + paragraph[end:]


def build_cleanup_prompt(
    raw_paragraph: str,
    translated_paragraph: str,
    regions: list[dict],
) -> str:
    """Xây prompt cleanup cho 1 đoạn văn.

    Áp dụng tag <HAN>...</HAN> cho tất cả region trong đoạn đó. Xử lý theo thứ tự
    `start` giảm dần để offset của region trước không bị lệch bởi tag của region sau
    (mỗi tag thêm 12 ký tự, làm hỏng vị trí các region phía sau nếu duyệt xuôi).
    """
    marked = translated_paragraph
    sorted_regions = sorted(regions, key=lambda r: r["start"], reverse=True)
    for r in sorted_regions:
        if r["full_paragraph"] == translated_paragraph:
            marked = _mark_region(marked, r)
    return CLEANUP_PROMPT.format(
        raw_paragraph=raw_paragraph,
        marked_text=marked,
    )


_REPLACE_TAGS = re.compile(r"<HAN>|</HAN>")


def _extract_replacement(response: str, original: str) -> str | None:
    """Trích xuất đoạn đã sửa từ response, fallback nếu AI trả nguyên bản."""
    cleaned = response.strip()

    # Bỏ code fence
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # Nếu response khác original (đã có thay đổi) -> dùng response
    if cleaned != original:
        # Bỏ tag HAN nếu AI quên xoá
        return _REPLACE_TAGS.sub("", cleaned)

    return None


def cleanup_paragraph(
    raw_paragraph: str,
    translated_paragraph: str,
    regions: list[dict],
    ai_cfg: OpenAIConfig,
) -> tuple[str, int]:
    """Gửi 1 đoạn văn có Hán cho AI sửa, trả (đoạn đã_sửa, số_chỗ_thực_sự_sửa).

    `fixed_count` đếm số region mà văn bản sau cleanup khác trước cleanup — không
    phải `len(regions)` (vì AI có thể chỉ sửa 1 trong 2 region, hoặc không sửa gì).
    Trả (translated_paragraph, 0) nếu không sửa được gì.
    """
    han_before = len(_HAN_RE.findall(translated_paragraph))
    if han_before == 0:
        return translated_paragraph, 0

    prompt = build_cleanup_prompt(raw_paragraph, translated_paragraph, regions)
    try:
        response = openai_client.run_chat(ai_cfg, prompt)
    except RuntimeError:
        return translated_paragraph, 0

    fixed = _extract_replacement(response, translated_paragraph)
    if fixed is None:
        return translated_paragraph, 0

    han_after = len(_HAN_RE.findall(fixed))
    actual_fixes = max(0, han_before - han_after)
    return fixed, actual_fixes


def cleanup_chapter(
    raw: str,
    translated: str,
    ai_cfg: OpenAIConfig,
    log: Callable[[str], None] | None = None,
    max_chars: int = 0,
    retries: int = 1,
) -> tuple[str, int, list[str]]:
    """Sửa toàn bộ chương: phát hiện Hán, gọi AI sửa từng đoạn.

    Args:
        raw: Bản gốc Trung (dùng làm ngữ cảnh cho AI).
        translated: Bản dịch Việt cần sửa.
        ai_cfg: Cấu hình AI (OpenAI-compatible).
        log: Callback log.
        max_chars: Nếu > 0, dừng gửi AI khi bản dịch vượt ngưỡng ký tự
            (chapter quá dài, chỉ xử lý phần đầu có Hán). 0 = không giới hạn.
        retries: Số lần thử lại khi vẫn còn Hán sau lần cleanup đầu (1 = thử 1 lần,
            không retry thêm; 0 = không thử). Mỗi lần retry lại quét từ đầu chapter.

    Trả (translated_đã_sửa, tổng_số_chỗ_sửa_thực_tế, warnings).
    Không sửa gì nếu không có Hán.
    """
    log = log or (lambda _: None)
    retries = max(0, int(retries))
    total_attempts = 1 + retries
    total_fixed = 0
    warnings: list[str] = []
    current = translated
    original_han = count_han(translated)
    if original_han == 0:
        return translated, 0, []

    if max_chars > 0 and len(current) > max_chars:
        log(f"  … chương dài {len(current)} ký tự > max_chars={max_chars}, dừng cleanup")
        return current, 0, ["Bỏ qua: chương dài quá max_chars"]

    for attempt in range(total_attempts):
        regions = find_han_regions(current)
        if not regions:
            if attempt > 0:
                log(f"  … retry {attempt}: đã sạch Hán")
            break

        raw_paras = raw.split("\n")
        translated_paras = current.split("\n")
        attempt_fixed = 0

        processed_para_indices: set[int] = set()
        for region in regions:
            para_idx = region["paragraph_index"]
            if para_idx in processed_para_indices:
                continue
            processed_para_indices.add(para_idx)

            para_regions = [r for r in regions if r["paragraph_index"] == para_idx]
            translated_para = translated_paras[para_idx] if para_idx < len(translated_paras) else ""
            raw_para = raw_paras[para_idx] if para_idx < len(raw_paras) else ""

            if not translated_para.strip():
                continue

            fixed_para, fixed_count = cleanup_paragraph(
                raw_para, translated_para, para_regions, ai_cfg
            )
            if fixed_count > 0 and fixed_para != translated_para:
                translated_paras[para_idx] = fixed_para
                attempt_fixed += fixed_count
                log(f"  … sửa {fixed_count} chỗ Hán ở đoạn {para_idx + 1}")
            elif fixed_para != translated_para:
                # AI trả về khác nhưng không giảm Hán — vẫn ghi nhận thay đổi nhưng không tính fix
                translated_paras[para_idx] = fixed_para

        current = "\n".join(translated_paras)
        total_fixed += attempt_fixed
        if attempt_fixed == 0:
            log(f"  … retry {attempt}: AI không sửa thêm được, dừng retry")
            break

    han_final = count_han(current)
    if han_final > 0:
        warnings.append(f"Còn {han_final} ký tự Hán sau {total_attempts} lần cleanup")

    return current, total_fixed, warnings


def count_han(text: str) -> int:
    """Đếm số ký tự Trung Quốc trong text."""
    return len(_HAN_RE.findall(text))
