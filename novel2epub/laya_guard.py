"""PoC: ý kiến thứ hai cho "AI tự động duyệt" bằng Laya
(https://huggingface.co/convaiinnovations/laya) — model phân loại/quyết định
chạy local, KHÔNG sinh text.

Chế độ LOG-ONLY: kết quả Laya chỉ ghi log + outcome để đo độ khớp với guard
xác định (`split_auto_approvable`), KHÔNG chặn tự duyệt. Bật bằng env:

    LAYA_BASE_URL=http://localhost:8000   # laya-serve (xem model card)
    LAYA_API_KEY=...                      # nếu server đặt LAYA_API_KEY
    LAYA_THRESHOLD=0.8                    # ngưỡng tin cậy (chỉ để log)
    LAYA_TIMEOUT=30

Bỏ trống LAYA_BASE_URL = tắt hoàn toàn, không tốn gì. Mọi lỗi gọi server đều
bị nuốt kèm log — guard xác định vẫn là chốt chặn duy nhất.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class LayaGuardConfig:
    """Cấu hình PoC guard Laya. Mặc định tắt (`base_url` rỗng)."""

    base_url: str = ""
    api_key: str = ""
    threshold: float = 0.8
    timeout_seconds: int = 30

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip())

    @classmethod
    def from_env(cls, environ: dict | None = None) -> "LayaGuardConfig":
        env = environ if environ is not None else os.environ
        try:
            threshold = float(env.get("LAYA_THRESHOLD", "0.8"))
        except (TypeError, ValueError):
            threshold = 0.8
        try:
            timeout = int(env.get("LAYA_TIMEOUT", "30"))
        except (TypeError, ValueError):
            timeout = 30
        return cls(
            base_url=str(env.get("LAYA_BASE_URL", "") or "").strip().rstrip("/"),
            api_key=str(env.get("LAYA_API_KEY", "") or ""),
            threshold=threshold,
            timeout_seconds=timeout,
        )


# Câu hỏi 2 đáp án với key trung tính ("A"/"B") — model card khuyến nghị thay
# vì `noul` vì `noul` hay kẹt ở đáp án "no" trên checkpoint tiếng Anh.
GLOSSARY_QUESTION = {
    "type": "choice",
    "instructions": "Is the Vietnamese glossary translation correct and consistent for this Chinese term?",
    "criteria": {
        "A": "yes, the Vietnamese translation is correct, natural and consistent",
        "B": "no, the translation is wrong, suspicious or inconsistent",
    },
}

# Số mục tối đa mỗi request: state multilingual ~768 token cho nội dung sau khi
# trừ ngân sách câu hỏi — mỗi mục ~1 dòng nên chunk nhỏ để khỏi bị cắt ngầm.
CHUNK_SIZE = 20


def _format_story_line(story: dict | None) -> str:
    if not story:
        return ""
    title = str(story.get("title", "") or "").strip()
    author = str(story.get("author", "") or "").strip()
    if title and author:
        return f"Story: {title} by {author}."
    return f"Story: {title or author}." if (title or author) else ""


def build_state(items: list[dict], story: dict | None = None) -> str:
    """Gom nhiều mục thành MỘT state, mỗi mục một dòng để Laya chấm hàng loạt."""
    lines = [f"- {i['source']} = {i['target']}" for i in items]
    story_line = _format_story_line(story)
    if story_line:
        lines.append(story_line)
    return "\n".join(lines)


def chunk_items(items: list[dict], size: int = CHUNK_SIZE) -> list[list[dict]]:
    """Chia mục thành các lô vừa ngân sách state của một request."""
    size = max(1, int(size or CHUNK_SIZE))
    return [items[i : i + size] for i in range(0, len(items), size)]


def _headers(cfg: LayaGuardConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    return headers


def _parse_answers(data: dict, keys: list[str]) -> dict[str, dict]:
    """Trích `{qkey: {verdict, confidence}}` từ response laya-serve
    (`{answers: {q: {choice, confidence}}}`), chịu được field thiếu."""
    answers = data.get("answers", {}) if isinstance(data, dict) else {}
    out: dict[str, dict] = {}
    for key in keys:
        node = answers.get(key, {})
        if not isinstance(node, dict):
            continue
        choice = str(node.get("choice", "")).strip()
        try:
            confidence = float(node.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if choice:
            out[key] = {"verdict": choice, "confidence": confidence}
    return out


def score_terms(
    cfg: LayaGuardConfig,
    items: list[dict],
    story: dict | None = None,
    *,
    log=None,
) -> list[dict]:
    """Hỏi Laya từng mục glossary có đúng không, trả
    `[{source, verdict ("A"/"B"), confidence}]`.

    Mỗi chunk là MỘT request (state nhiều dòng + 1 câu hỏi/mục) nên N mục chỉ
    tốn ceil(N/20) forward pass. Lỗi request/parse ở chunk nào thì bỏ chunk đó
    kèm log — PoC log-only không được làm hỏng job chính.
    """
    import requests

    opinions: list[dict] = []
    for ci, chunk in enumerate(chunk_items(items), 1):
        keys = [f"q{i}" for i in range(len(chunk))]
        payload = {
            "state": {"terms": build_state(chunk, story)},
            "questions": {key: dict(GLOSSARY_QUESTION) for key in keys},
        }
        if log:
            log(f"[laya-guard] Lô {ci}: hỏi {len(chunk)} mục…")
        try:
            resp = requests.post(
                cfg.base_url + "/v1/systemone",
                json=payload,
                headers=_headers(cfg),
                timeout=cfg.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 — PoC không được sập job
            if log:
                log(f"[laya-guard] Lô {ci} lỗi: {exc}")
            continue
        parsed = _parse_answers(data, keys)
        for key, item in zip(keys, chunk):
            node = parsed.get(key)
            if node is None:
                if log:
                    log(f"[laya-guard] Mục {item['source']!r}: server không trả lời.")
                continue
            opinions.append(
                {"source": item["source"], "verdict": node["verdict"], "confidence": node["confidence"]}
            )
    return opinions


def merge_opinions(
    gate: dict,
    opinions: list[dict],
    threshold: float = 0.8,
) -> dict:
    """Gắn ý kiến Laya vào kết quả guard xác định (thuần dữ liệu, không I/O).

    Mỗi mục trong `gate["approved"]`/`gate["held"]` được thêm `laya` là
    `{"verdict", "confidence", "agrees"}` (`agrees=True` khi Laya verdict "A"
    với confidence >= threshold đối với mục approved, hoặc verdict "B" đối với
    mục held). Mục Laya không trả lời được mang `laya: None`. Trả
    `{"approved": [...], "held": [...], "agreement": float|None}` — `agreement`
    là tỉ lệ mục Laya đồng ý với guard, None khi chưa có ý kiến nào.
    """
    by_source = {o["source"]: o for o in opinions if isinstance(o, dict)}
    total = agree = 0

    def _annotate(rows: list[dict], expect_ok: bool) -> list[dict]:
        nonlocal total, agree
        out = []
        for row in rows:
            row = dict(row)
            op = by_source.get(row.get("source", ""))
            if op is None:
                row["laya"] = None
            else:
                verdict_ok = str(op.get("verdict", "")).upper() == "A"
                try:
                    confidence = float(op.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                agrees = (verdict_ok == expect_ok) and (
                    confidence >= threshold if verdict_ok else True
                )
                total += 1
                agree += 1 if agrees else 0
                row["laya"] = {
                    "verdict": op.get("verdict", ""),
                    "confidence": confidence,
                    "agrees": agrees,
                }
            out.append(row)
        return out

    approved = _annotate(list(gate.get("approved", [])), expect_ok=True)
    held = _annotate(list(gate.get("held", [])), expect_ok=False)
    return {
        "approved": approved,
        "held": held,
        "agreement": (agree / total) if total else None,
    }
