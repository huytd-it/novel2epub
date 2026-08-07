"""Phát hiện và sửa chữa ký tự Trung Quốc còn sót trong bản dịch.

Luồng xử lý:
1. Quét bản dịch → tìm đoạn chứa ký tự Hán
2. Gom TẤT CẢ đoạn có vấn đề vào 1 prompt, gửi AI sửa trong 1 request
   (chia thêm request chỉ khi tổng payload vượt max_chars)
3. Parse các khối <DOAN id="N"> trong response, thay chính xác vào từng đoạn
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


def _mark_paragraph(paragraph: str, regions: list[dict]) -> str:
    """Đánh dấu tất cả vùng Hán của 1 đoạn bằng <HAN>...</HAN>.

    Xử lý theo thứ tự `start` giảm dần để offset của region trước không bị lệch
    bởi tag của region sau (mỗi tag thêm 12 ký tự, làm hỏng vị trí các region
    phía sau nếu duyệt xuôi).
    """
    marked = paragraph
    sorted_regions = sorted(regions, key=lambda r: r["start"], reverse=True)
    for r in sorted_regions:
        if r["full_paragraph"] == paragraph:
            marked = _mark_region(marked, r)
    return marked


def build_cleanup_prompt(
    raw_paragraph: str,
    translated_paragraph: str,
    regions: list[dict],
) -> str:
    """Xây prompt cleanup cho 1 đoạn văn (đường gọi từng-đoạn cũ)."""
    return CLEANUP_PROMPT.format(
        raw_paragraph=raw_paragraph,
        marked_text=_mark_paragraph(translated_paragraph, regions),
    )


BATCH_CLEANUP_PROMPT = """Bạn là biên tập viên truyện dịch Trung -> Việt, chuyên sửa các lỗi sót chữ Hán.

Dưới đây là {count} đoạn văn trích từ CÙNG MỘT chương bản dịch tiếng Việt. Mỗi đoạn còn chứa ký tự/ký hiệu Trung Quốc được đánh dấu bằng <HAN>...</HAN>, kèm bản gốc tiếng Trung (nếu có) để đối chiếu ngữ cảnh.

NHIỆM VỤ: Với TỪNG đoạn, chỉ sửa các phần được đánh dấu <HAN>...</HAN> thành tiếng Việt tự nhiên, GIỮ NGUYÊN phần còn lại.

NGUYÊN TẮC:
- Không thay đổi bất kỳ chữ nào ngoài vùng <HAN>...</HAN>.
- Nếu cả câu cần viết lại cho mượt vì vùng <HAN> nằm giữa câu, chỉ sửa vùng đó và tối thiểu từ xung quanh để câu tự nhiên.
- KHÔNG thêm lời mở đầu, giải thích, code fence.
- KHÔNG dùng định dạng song ngữ.

ĐỊNH DẠNG TRẢ LỜI (bắt buộc): với MỖI đoạn trả về đúng một khối, đủ {count} khối, giữ nguyên id:
<DOAN id="N">
toàn bộ đoạn N đã sửa (không còn tag HAN)
</DOAN>
KHÔNG thêm bất kỳ nội dung nào ngoài các khối <DOAN>.

{items}"""

_BATCH_ITEM_TEMPLATE = """=== ĐOẠN id={id} ===
--- Gốc Trung (đối chiếu) ---
{raw}
--- Bản dịch cần sửa (vùng Hán đã đánh dấu) ---
{marked}
"""

_DOAN_BLOCK_RE = re.compile(r'<DOAN\s+id="?(\d+)"?\s*>\s*(.*?)\s*</DOAN>', re.S | re.I)


def build_batch_cleanup_prompt(items: list[dict]) -> str:
    """Xây 1 prompt duy nhất chứa TẤT CẢ đoạn còn Hán của chương.

    `items`: list dict với keys `para_idx` (0-based), `raw`, `marked`.
    Id hiển thị cho AI là para_idx + 1 (khớp số đoạn trong log).
    """
    rendered = "\n".join(
        _BATCH_ITEM_TEMPLATE.format(
            id=it["para_idx"] + 1,
            raw=it["raw"] or "(không có)",
            marked=it["marked"],
        )
        for it in items
    )
    return BATCH_CLEANUP_PROMPT.format(count=len(items), items=rendered)


def parse_batch_response(response: str, items: list[dict]) -> dict[int, str]:
    """Parse response batch → {para_idx: đoạn_đã_sửa}.

    Chỉ nhận id có trong `items`; bỏ khối mà nội dung y nguyên bản gốc (AI noop).
    Fallback: nếu AI không trả khối <DOAN> nào và batch chỉ có 1 đoạn, coi toàn
    bộ response là đoạn đã sửa (kiểu trả lời của prompt từng-đoạn cũ).
    """
    by_idx = {it["para_idx"]: it for it in items}
    fixes: dict[int, str] = {}
    blocks = _DOAN_BLOCK_RE.findall(response)
    for id_str, body in blocks:
        para_idx = int(id_str) - 1
        item = by_idx.get(para_idx)
        if item is None:
            continue
        fixed = _REPLACE_TAGS.sub("", body.strip())
        if fixed and fixed != item["original"]:
            fixes[para_idx] = fixed
    if not blocks and len(items) == 1:
        item = items[0]
        fixed = _extract_replacement(response, item["original"])
        if fixed:
            fixes[item["para_idx"]] = fixed
    return fixes


def _pack_batches(items: list[dict], max_chars: int) -> list[list[dict]]:
    """Chia items thành các batch có tổng payload ≤ max_chars (0 = 1 batch duy nhất).

    Mục tiêu là 1 request cho cả chương; chỉ chia thêm khi tổng vượt ngân sách.
    Item đơn lẻ vượt ngân sách vẫn được gửi thành batch riêng (đã có guard chặn
    đoạn quá dài ở cleanup_chapter trước khi tới đây).
    """
    if max_chars <= 0:
        return [items] if items else []
    batches: list[list[dict]] = []
    cur: list[dict] = []
    cur_size = 0
    for it in items:
        size = len(it["marked"]) + len(it["raw"])
        if cur and cur_size + size > max_chars:
            batches.append(cur)
            cur, cur_size = [], 0
        cur.append(it)
        cur_size += size
    if cur:
        batches.append(cur)
    return batches


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
    """Sửa toàn bộ chương: gom TẤT CẢ đoạn còn Hán, gửi AI sửa trong 1 request.

    Args:
        raw: Bản gốc Trung (dùng làm ngữ cảnh cho AI).
        translated: Bản dịch Việt cần sửa.
        ai_cfg: Cấu hình AI (OpenAI-compatible).
        log: Callback log.
        max_chars: Nếu > 0, là ngân sách payload cho mỗi request: đoạn văn đơn lẻ
            dài hơn ngưỡng bị bỏ qua; tổng các đoạn vượt ngân sách thì chia thành
            nhiều request. 0 = không giới hạn (luôn đúng 1 request cho cả chương).
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

    skipped_long_paras: set[int] = set()

    for attempt in range(total_attempts):
        regions = find_han_regions(current)
        if not regions:
            if attempt > 0:
                log(f"  … retry {attempt}: đã sạch Hán")
            break

        raw_paras = raw.split("\n")
        translated_paras = current.split("\n")

        # Gom mỗi đoạn có Hán thành 1 item để gửi chung trong 1 request.
        items: list[dict] = []
        seen_para_indices: set[int] = set()
        for region in regions:
            para_idx = region["paragraph_index"]
            if para_idx in seen_para_indices:
                continue
            seen_para_indices.add(para_idx)

            translated_para = translated_paras[para_idx] if para_idx < len(translated_paras) else ""
            raw_para = raw_paras[para_idx] if para_idx < len(raw_paras) else ""

            if not translated_para.strip():
                continue

            if max_chars > 0 and len(translated_para) > max_chars:
                if para_idx not in skipped_long_paras:
                    skipped_long_paras.add(para_idx)
                    log(f"  … đoạn {para_idx + 1} dài {len(translated_para)} ký tự > max_chars={max_chars}, bỏ qua đoạn này")
                continue

            para_regions = [r for r in regions if r["paragraph_index"] == para_idx]
            items.append({
                "para_idx": para_idx,
                "raw": raw_para,
                "marked": _mark_paragraph(translated_para, para_regions),
                "original": translated_para,
            })

        if not items:
            break

        batches = _pack_batches(items, max_chars)
        if len(items) > 1:
            log(f"  … gửi {len(items)} đoạn còn Hán trong {len(batches)} request")

        attempt_fixed = 0
        for batch in batches:
            prompt = build_batch_cleanup_prompt(batch)
            try:
                response = openai_client.run_chat(ai_cfg, prompt)
            except RuntimeError:
                continue
            fixes = parse_batch_response(response, batch)
            for item in batch:
                fixed = fixes.get(item["para_idx"])
                if fixed is None:
                    continue
                han_delta = max(
                    0,
                    len(_HAN_RE.findall(item["original"])) - len(_HAN_RE.findall(fixed)),
                )
                # Ghi nhận thay đổi kể cả khi không giảm Hán (AI sửa văn phong
                # quanh vùng đánh dấu), nhưng chỉ tính fix khi Hán giảm thật.
                translated_paras[item["para_idx"]] = fixed
                if han_delta:
                    attempt_fixed += han_delta
                    log(f"  … sửa {han_delta} chỗ Hán ở đoạn {item['para_idx'] + 1}")

        current = "\n".join(translated_paras)
        total_fixed += attempt_fixed
        if attempt_fixed == 0:
            log(f"  … retry {attempt}: AI không sửa thêm được, dừng retry")
            break

    if skipped_long_paras:
        warnings.append(
            f"Bỏ qua {len(skipped_long_paras)} đoạn dài quá max_chars={max_chars}"
        )

    han_final = count_han(current)
    if han_final > 0:
        warnings.append(f"Còn {han_final} ký tự Hán sau {total_attempts} lần cleanup")

    return current, total_fixed, warnings


def _is_word_char(char: str) -> bool:
    """Ký tự có thể dính vào từ Việt/Latin ở ranh giới replacement."""
    return bool(char) and (char.isalpha() or char.isdigit()) and not _HAN_RE.match(char)


def splice_local_mt_translation(text: str, start: int, end: int, replacement: str) -> str:
    """Thay một vùng Hán và thêm space ở ranh giới từ khi thực sự cần.

    Chỉ đụng khoảng trắng sát vùng thay thế; không normalize toàn paragraph và
    không tạo khoảng trắng thừa cạnh dấu câu hoặc ngoặc.
    """
    replacement = replacement.strip()
    if not replacement:
        return text
    before = text[:start]
    after = text[end:]
    if before and not before[-1].isspace() and _is_word_char(before[-1]) and _is_word_char(replacement[0]):
        replacement = " " + replacement
    if after and not after[0].isspace() and _is_word_char(replacement[-1]) and _is_word_char(after[0]):
        replacement += " "
    return before + replacement + after


def cleanup_han_with_local_mt(
    translated: str,
    translate: Callable[[str], str],
    log: Callable[[str], None] | None = None,
) -> tuple[str, int, list[str]]:
    """Dịch riêng từng vùng còn Hán bằng Local MT, giữ nguyên phần Việt."""
    log = log or (lambda _: None)
    regions = find_han_regions(translated)
    if not regions:
        return translated, 0, []
    current = translated
    fixed = 0
    warnings: list[str] = []
    # Offset được tính trên text ban đầu nên thay từ phải sang trái.
    for region in sorted(regions, key=lambda item: (item["paragraph_index"], item["start"]), reverse=True):
        source = region["chinese_text"]
        try:
            replacement = (translate(source) or "").strip()
        except Exception as exc:
            warnings.append(f"Local MT lỗi với {source!r}: {exc}")
            continue
        if not replacement or replacement == source:
            warnings.append(f"Local MT không dịch được {source!r}")
            continue

        # Chuyển offset paragraph thành offset toàn chapter.
        lines = current.split("\n")
        para_index = region["paragraph_index"]
        if para_index >= len(lines):
            continue
        paragraph = lines[para_index]
        start, end = region["start"], region["end"]
        if paragraph[start:end] != source:
            warnings.append(f"Bỏ qua vùng đã thay đổi {source!r}")
            continue
        lines[para_index] = splice_local_mt_translation(paragraph, start, end, replacement)
        current = "\n".join(lines)
        fixed += max(0, count_han(source) - count_han(replacement))
        log(f"  … {source!r} → {replacement!r}")
    return current, fixed, warnings


def count_han(text: str) -> int:
    """Đếm số ký tự Trung Quốc trong text."""
    return len(_HAN_RE.findall(text))
