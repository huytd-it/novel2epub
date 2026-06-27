"""Token-aware chunking for Marian models (ported from HachimiMT HF Space)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

SENTENCE_RE = re.compile(
    r".+?(?:[。！？!?；;…]+[」』）》】”’\"']*|$)",
    re.S,
)
HEADING_RE = re.compile(r"^第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷部篇]")
METADATA_RE = re.compile(r"^(?:书名|作者|简介|内容简介|作品简介)\s*[:：]")


def is_hard_boundary_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped or "\n" in stripped:
        return False
    if METADATA_RE.match(stripped):
        return True
    if len(stripped) > 32:
        return False
    if re.search(r"[。！？!?；;，,：:\"“”]", stripped):
        return False
    return bool(HEADING_RE.match(stripped))


def source_token_ids(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_length: int,
    truncation: bool,
) -> list[int]:
    token_ids = tokenizer(
        text,
        truncation=truncation,
        max_length=max_length,
    )["input_ids"]
    if tokenizer.pad_token_id is not None:
        token_ids = [tid for tid in token_ids if tid != tokenizer.pad_token_id]
    return token_ids


def source_token_count(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_length: int,
) -> int:
    return len(source_token_ids(tokenizer, text, max_length=max_length, truncation=False))


def char_chunks(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if source_token_count(tokenizer, remaining, max_length=max_tokens) <= max_tokens:
            chunks.append(remaining)
            break
        low, high = 1, len(remaining)
        best = 1
        while low <= high:
            middle = (low + high) // 2
            candidate = remaining[:middle]
            if source_token_count(tokenizer, candidate, max_length=max_tokens) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        chunks.append(remaining[:best])
        remaining = remaining[best:]
    return chunks


def sentence_chunks(
    tokenizer: PreTrainedTokenizerBase,
    line: str,
    *,
    max_tokens: int,
) -> list[str]:
    if source_token_count(tokenizer, line, max_length=max_tokens) <= max_tokens:
        return [line]
    pieces = [match.group(0) for match in SENTENCE_RE.finditer(line)]
    if not pieces:
        return char_chunks(tokenizer, line, max_tokens=max_tokens)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if source_token_count(tokenizer, piece, max_length=max_tokens) > max_tokens:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(char_chunks(tokenizer, piece, max_tokens=max_tokens))
            continue
        candidate = current + piece
        if current and source_token_count(tokenizer, candidate, max_length=max_tokens) > max_tokens:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _layout_lines(text: str) -> list[str]:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_sentence_lines_with_plan(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> tuple[list[str], list[list[int] | None]]:
    chunks: list[str] = []
    plan: list[list[int] | None] = []
    for line in _layout_lines(text):
        stripped = line.strip()
        if not stripped:
            plan.append(None)
            continue
        line_chunks = sentence_chunks(tokenizer, stripped, max_tokens=max_tokens)
        indices = list(range(len(chunks), len(chunks) + len(line_chunks)))
        chunks.extend(line_chunks)
        plan.append(indices)
    return chunks, plan


def split_paragraphs_with_plan(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
) -> tuple[list[str], list[tuple[int, ...]]]:
    chunks: list[str] = []
    plan: list[tuple[int, ...]] = []
    buffered_lines: list[str] = []
    buffered_indices: list[int] = []

    def flush_buffer() -> None:
        if not buffered_lines:
            return
        chunks.append("\n".join(buffered_lines))
        plan.append(tuple(buffered_indices))
        buffered_lines.clear()
        buffered_indices.clear()

    def add_line_chunk(line_index: int, line: str) -> None:
        for piece in sentence_chunks(tokenizer, line, max_tokens=max_tokens):
            chunks.append(piece)
            plan.append((line_index,))

    for line_index, line in enumerate(_layout_lines(text)):
        stripped = line.strip()
        if not stripped:
            flush_buffer()
            continue
        if is_hard_boundary_line(stripped):
            flush_buffer()
            add_line_chunk(line_index, stripped)
            continue
        if source_token_count(tokenizer, stripped, max_length=max_tokens) > max_tokens:
            flush_buffer()
            add_line_chunk(line_index, stripped)
            continue
        candidate_lines = [*buffered_lines, stripped]
        candidate = "\n".join(candidate_lines)
        if buffered_lines and source_token_count(tokenizer, candidate, max_length=max_tokens) > max_tokens:
            flush_buffer()
        buffered_lines.append(stripped)
        buffered_indices.append(line_index)
    flush_buffer()
    return chunks, plan


def split_for_translation(
    tokenizer: PreTrainedTokenizerBase,
    text: str,
    *,
    max_tokens: int,
    chunk_mode: str = "sentence",
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if chunk_mode == "paragraph":
        chunks, _plan = split_paragraphs_with_plan(tokenizer, text, max_tokens=max_tokens)
        return chunks
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        chunks.extend(sentence_chunks(tokenizer, line, max_tokens=max_tokens))
    return chunks
