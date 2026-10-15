"""Conservative, offline neutral-address editing; never infer speakers or relations."""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import Iterable, Literal
import uuid


RULE_VERSION = "neutral-dialogue-v2"
_PAIRS = {'"': '"', '“': '”', '«': '»', '「': '」', '『': '』'}
DialogueMarks = Literal["standard", "single_chinese", "parentheses"]
DIALOGUE_MARK_MODES = ("standard", "single_chinese", "parentheses")
_MARK_PAIRS = {
    "standard": _PAIRS,
    "single_chinese": {"'": "'", "‘": "’", "“": "”", "「": "」", "『": "』"},
    "parentheses": {"(": ")", "（": "）"},
}
_ALL_PAIRS = {**_PAIRS, **_MARK_PAIRS["single_chinese"], **_MARK_PAIRS["parentheses"]}
_SINGULAR = {"tôi": "ta", "tao": "ta", "tớ": "ta", "mày": "ngươi"}
_PLURAL = {
    f"{group} {pronoun}": "các ngươi" if pronoun == "mày" else "bọn ta"
    for group in ("chúng", "bọn", "tụi")
    for pronoun in _SINGULAR
}
_RULES = {**_PLURAL, **_SINGULAR}
_TOKENS = re.compile(
    r"(?<!\w)(?:" + "|".join(
        re.escape(key).replace(r"\ ", r"[ \t]+")
        for key in sorted(_RULES, key=len, reverse=True)
    ) + r")(?!\w)", re.IGNORECASE,
)
# Homographs: replacing these would corrupt meaning even inside dialogue.
_EXCEPTIONS = re.compile(
    r"(?<!\w)(?:cái[ \t]+tôi|đầy[ \t]+tớ|tôi[ \t]+tớ|"
    r"thanh[ \t]+tao|tao[ \t]+(?:nhã|đàn|nhân|phùng)|"
    r"tôi[ \t]+(?:luyện|thép|kim[ \t]+loại)|"
    r"(?:lông|chân|đôi|hàng|cặp|nhíu|cau|nhướng|nhướn|rướn)[ \t]+mày|"
    r"mày[ \t]+(?:kiếm|liễu))(?!\w)", re.IGNORECASE,
)


@dataclass(frozen=True)
class PronounChange:
    start: int
    end: int
    before: str
    after: str


@dataclass(frozen=True)
class PronounResult:
    text: str
    changes: tuple[PronounChange, ...]


def _dialogue_spans(text: str, dialogue_marks: DialogueMarks = "standard"):
    """Only balanced, non-nested quotes on one line. Ambiguity means abstain."""
    if dialogue_marks not in DIALOGUE_MARK_MODES:
        raise ValueError("Kiểu dấu bao quanh không hợp lệ.")
    selected = _MARK_PAIRS[dialogue_marks]
    # Strict modes also recognize unselected wrappers, so a nested selected
    # marker cannot make part of an ambiguous outer span eligible.
    pairs = _PAIRS if dialogue_marks == "standard" else _ALL_PAIRS
    closers = set(pairs.values())
    offset = 0
    stack: list[str] = []
    nested = False
    eligible = False
    for line in text.splitlines(keepends=True):
        carried = bool(stack)
        spans = []
        start = 0
        malformed = False
        escaped = False
        for pos, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char in {"'", "‘", "’"}:
                previous = line[pos - 1] if pos else ""
                following = line[pos + 1] if pos + 1 < len(line) else ""
                # don't / O’Connor are words, not dialogue boundaries.
                if previous.isalnum() and following.isalnum():
                    continue
                if char == "'" and previous.isalnum() and (not stack or stack[-1] != "'"):
                    continue
            if stack and char == stack[-1]:
                stack.pop()
                if not stack and not nested and eligible:
                    spans.append((offset + start, offset + pos))
            elif char in pairs:
                if not stack:
                    start = pos + 1
                    nested = False
                    eligible = char in selected
                else:
                    nested = True
                stack.append(pairs[char])
            elif char in closers:
                malformed = True
        if not carried and not stack and not malformed:
            yield from spans
        offset += len(line)


def normalize_pronouns(
    text: str, *, protected_terms: Iterable[str] = (), dialogue_marks: DialogueMarks = "standard",
) -> PronounResult:
    """Return exact-offset edits; keep narration, relations and ambiguous forms intact.

    This is a style heuristic, not semantic correction. A preview is mandatory
    in the workflow because quoted thoughts/terms can resemble speech.
    """
    protected = [(m.start(), m.end()) for m in _EXCEPTIONS.finditer(text)]
    for term in set(protected_terms):
        if term:
            protected.extend(
                (m.start(), m.end())
                for m in re.finditer(re.escape(term), text, re.IGNORECASE)
            )
    changes = []
    for start, end in _dialogue_spans(text, dialogue_marks):
        for match in _TOKENS.finditer(text, start, end):
            if any(match.start() < right and match.end() > left for left, right in protected):
                continue
            before = match.group()
            key = re.sub(r"[ \t]+", " ", before.lower())
            after = _RULES[key]
            if before.isupper():
                after = after.upper()
            elif before[0].isupper():
                after = after[0].upper() + after[1:]
            changes.append(PronounChange(match.start(), match.end(), before, after))
    output = text
    for change in reversed(changes):
        output = output[:change.start] + change.after + output[change.end:]
    return PronounResult(output, tuple(changes))


def normalize_book_pronouns(
    storage, *, branch: str, start: int | None = None, end: int | None = None,
    apply: bool = False, log=print, dialogue_marks: DialogueMarks = "standard",
) -> dict:
    """Explicit branch, preview without writes, CAS commits with immutable history.

    Applying is per chapter, not all-or-nothing across the book. A conflict
    stops the operation; already committed chapters keep their history.
    """
    from .chapter_versions import ChapterVersionService

    if branch not in {"ai", "local_mt"}:
        raise ValueError("Chọn nhánh ai hoặc local_mt.")
    if dialogue_marks not in DIALOGUE_MARK_MODES:
        raise ValueError("Kiểu dấu bao quanh không hợp lệ.")
    if (start is not None and start < 0) or (end is not None and end < 0):
        raise ValueError("Index chương không được âm.")
    if start is not None and end is not None and start > end:
        raise ValueError("--from không được lớn hơn --to.")
    manifest = storage.load_manifest()
    if manifest is None:
        raise RuntimeError("Không tìm thấy ebook/manifest.")
    protected_terms = [
        term for entity in storage.read_merged_entities() if entity.protect
        for term in (entity.source, entity.target) if term
    ]
    service = ChapterVersionService(storage)
    summary = {"scanned": 0, "changed": 0, "replacements": 0, "applied": 0}
    log(f"Quy tắc cục bộ, không gọi AI. Dấu bao quanh: {dialogue_marks}; chỉ xử lý cặp cân bằng trên cùng dòng.")
    for chapter in manifest.chapters:
        if chapter.skipped or (start is not None and chapter.index < start) or (end is not None and chapter.index > end):
            continue
        if not storage.has_branch_text(chapter, branch):
            continue
        # Preview and no-op chapters must not heal/backfill history.
        base = None
        before = storage.read_branch_text(chapter, branch)
        result = normalize_pronouns(before, protected_terms=protected_terms, dialogue_marks=dialogue_marks)
        if apply and result.changes:
            base = service.read_document(chapter.index, branch)
            before = base.translated
            result = normalize_pronouns(before, protected_terms=protected_terms, dialogue_marks=dialogue_marks)
        summary["scanned"] += 1
        if not result.changes:
            continue
        summary["changed"] += 1
        summary["replacements"] += len(result.changes)
        label = f"{storage.slug}/{chapter.index}/{branch}"
        diff_lines = difflib.unified_diff(
            before.splitlines(keepends=True), result.text.splitlines(keepends=True),
            fromfile=f"{label}:before", tofile=f"{label}:after",
        )
        diff = "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in diff_lines
        )
        log(diff)
        if apply:
            service.commit_document(
                chapter_index=chapter.index, branch=branch,
                expected_revision=base.revision, expected_content_hash=base.content_hash,
                title=base.title, translated=result.text,
                client_operation_id=f"pronouns:{uuid.uuid4()}",
                kind="normalize_pronouns", message="Chuẩn hóa xưng hô ta/ngươi bằng quy tắc cục bộ",
                metadata={"rules": RULE_VERSION, "replacements": len(result.changes), "dialogue_marks": dialogue_marks},
            )
            summary["applied"] += 1
            log(f"Đã lưu chương {chapter.index}; có lịch sử phiên bản.")
    return summary
