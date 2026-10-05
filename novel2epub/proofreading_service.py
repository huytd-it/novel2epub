"""Orchestration soát lỗi publication, draft và candidate; SQLite là runtime duy nhất."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from uuid import uuid4

from . import build_validation as validation, openai_client, revisions
from .chapter_versions import ChapterVersionService
from .ops_baseline import full_content_hash, initialize_branch_revisions
from .proofreading import ProofreadingError, build_prompt, evidence_spans, fix_algorithms, selected_codes, validate_ai_edits


BOOK_CODES = {"identical_content", "number_missing", "number_duplicate", "number_descending"}


def book_check(storage) -> dict:
    manifest = storage.load_manifest()
    versions = storage.bulk_publication_versions()
    return validation.validate_book([{"index": ch.index, "title": versions[ch.index].title if versions.get(ch.index) else ch.title, "text": versions[ch.index].text if versions.get(ch.index) else "", "skipped": ch.skipped} for ch in manifest.chapters] if manifest else [])


def scan_book(storage, log=lambda _: None) -> dict:
    """Quét + lưu trạng thái lỗi hiện tại; không đổi nội dung hoặc gọi AI."""
    from .content_validation import refresh_book
    return refresh_book(storage, log)


def issue_confirmation(storage, report: dict) -> str:
    token = str(uuid4())
    snapshot_rows = [{k: v for k, v in c.items() if k not in {"text", "issues"}} for c in report["chapters"] if not c.get("error")]
    def update(current):
        tokens = {k: v for k, v in (current or {}).items() if v["expires"] > time.time()}
        if len(tokens) >= 20:
            tokens.pop(next(iter(tokens)))
        tokens[token] = {"expires": time.time() + 600, "chapters": snapshot_rows, "codes": report["codes"]}
        return tokens
    storage.update_extra_json("proofreading_confirmations", update)
    return token


def consume_confirmation(storage, token: str, chapters: list[dict], codes: list[str]) -> dict:
    confirmed = {}
    supplied = [{k: v for k, v in c.items() if k not in {"text", "issues"}} for c in chapters]
    def update(current):
        entry = (current or {}).get(token)
        if not entry or entry["expires"] <= time.time() or entry["chapters"] != supplied or entry["codes"] != codes:
            raise ProofreadingError("Xác nhận hết hạn/đã dùng hoặc tập index/mã lỗi/snapshot đã đổi — phân tích lại.")
        confirmed.update(entry)
        return {k: v for k, v in current.items() if k != token and v["expires"] > time.time()}
    storage.update_extra_json("proofreading_confirmations", update)
    return confirmed


def snapshot(storage, index: int) -> dict:
    ch = storage.get_chapter(index)
    if ch is None:
        raise ProofreadingError("Không tìm thấy chương.")
    if ch.skipped:
        raise ProofreadingError("Chương đang Bỏ qua; không soát lỗi hoặc áp dụng bản sửa.")
    publication = storage.publication_version(ch)
    if publication is None:
        raise ProofreadingError("Chưa có bản AI/Local MT hoàn chỉnh; không dùng active branch thay thế.")
    # Resolver title có thể fallback manifest; khóa canonical phải dùng title nhánh thực.
    title = storage.read_branch_title(ch, publication.branch)
    return {"index": index, "branch": publication.branch, "revision": publication.revision,
            "hash": full_content_hash(title, publication.text), "title": title, "display_title": publication.title, "text": publication.text}


def check_snapshot(storage, expected: dict) -> dict:
    current = snapshot(storage, expected["index"])
    if any(current[k] != expected[k] for k in ("branch", "revision", "hash")) or "display_title" in expected and current["display_title"] != expected["display_title"]:
        raise ProofreadingError("Nhánh/revision/nội dung xuất bản đã đổi — phân tích và tạo lại, không merge.")
    return current


def analyze(storage, indexes: list[int], codes: list[str] | None = None, drafts: dict | None = None) -> dict:
    if not isinstance(indexes, list) or not indexes or any(type(i) is not int or i < 0 for i in indexes):
        raise ProofreadingError("Cần danh sách index cụ thể; không mặc định toàn sách.")
    if len(indexes) != len(set(indexes)):
        raise ProofreadingError("Danh sách index bị trùng.")
    if codes is not None and not isinstance(codes, list):
        raise ProofreadingError("Danh sách mã lỗi không hợp lệ.")
    if drafts is not None and not isinstance(drafts, dict):
        raise ProofreadingError("Danh sách draft không hợp lệ.")
    if codes:
        selected_codes(codes)
    results = []
    book_issues = book_check(storage)["issues"] if not codes or BOOK_CODES.intersection(codes) else []
    for index in indexes:
        try:
            item = snapshot(storage, index)
            draft = (drafts or {}).get(str(index))
            if draft is not None:
                if not isinstance(draft, dict) or not isinstance(draft.get("text"), str) or draft.get("branch") != item["branch"] or draft.get("revision") != item["revision"]:
                    raise ProofreadingError("Draft không thuộc revision/nhánh xuất bản hiện tại; giữ draft, không ghi.")
                draft_title = draft.get("title", item["title"])
                if not isinstance(draft_title, str):
                    raise ProofreadingError("Tiêu đề draft không hợp lệ.")
                item.update(draft=True, draft_text=draft["text"], draft_title=draft_title, draft_hash=full_content_hash(draft_title, draft["text"]))
            ch = storage.get_chapter(index)
            report = validation.chapter_validation_report(ch, storage, storage.publication_version(ch), text_override=item.get("draft_text", item["text"]), title_override=item.get("draft_title"))
            item["issues"] = [i for i in report["issues"] if not codes or i["code"] in codes]
            item["issues"].extend({**i, "paraIndex": -1, "start": 0, "end": 0, "snippet": ""} for i in book_issues if i["index"] == index or index in i.get("related_indexes", []))
            results.append(item)
        except (ProofreadingError, ValueError) as exc:
            results.append({"index": index, "error": str(exc)})
    return {"chapters": results, "codes": codes or [], "contract": validation.validation_contract()}


def _commit(storage, base: dict, text: str, title: str, operation_id: str, candidate_id=None, codes=None):
    initialize_branch_revisions(storage, branches=[base["branch"]], chapter_indexes=[base["index"]])
    return ChapterVersionService(storage).commit_document(
        chapter_index=base["index"], branch=base["branch"], expected_revision=base["revision"],
        expected_content_hash=base["hash"], title=title, translated=text,
        client_operation_id=operation_id, kind="proofreading", message="Soát lỗi: " + ("AI đã duyệt" if candidate_id else "thuật toán đã xác nhận"),
        expected_publication_branch=base["branch"], proofreading_candidate_id=candidate_id,
        expected_publication_title=base.get("display_title"),
        metadata={"source": "proofreading_ai_approved" if candidate_id else "proofreading_algorithm_confirmed", "selected_codes": codes or [], "candidate_id": candidate_id},
    )


def run(storage, cfg, chapters: list[dict], codes: list[str], *, instructions: str = "", log=lambda _: None, call_ai=None, run_id: str = "") -> dict:
    selected = selected_codes(codes)
    if not isinstance(chapters, list) or not chapters:
        raise ProofreadingError("Chưa xác nhận tập chương.")
    results = []
    book_issues = book_check(storage)["issues"] if BOOK_CODES.intersection(codes) else []
    log(f"[proofreading] BẮT ĐẦU run={run_id or '-'}; mã={','.join(codes)}; index={','.join(str(c.get('index')) for c in chapters)}")
    for expected in chapters:
        result = {"index": expected.get("index"), "candidate_id": None, "codes": codes, "audit": []}
        def record(stage, message):
            # Không ghi nội dung chương, prompt, provider exception hoặc credential.
            line = f"[proofreading] Chương {result['index']} | mã={','.join(codes)} | {stage}: {message}"
            result["audit"].append(line)
            log(line)
        try:
            base = check_snapshot(storage, expected)
            record("NGUỒN", f"nhánh={base['branch']}; revision={base['revision']}; hash={base['hash']}")
            draft = bool(expected.get("draft"))
            text = expected.get("draft_text") if draft else base["text"]
            input_title = expected.get("draft_title", base["title"]) if draft else base["title"]
            if not isinstance(text, str) or not isinstance(input_title, str) or draft and expected.get("draft_hash") != full_content_hash(input_title, text):
                raise ProofreadingError("Draft hash không khớp.")
            fixed = fix_algorithms(text, codes, input_title if draft else base["display_title"])
            ch = storage.get_chapter(base["index"])
            publication = storage.publication_version(ch)
            shared_remaining = validation.chapter_validation_report(ch, storage, publication, text_override=fixed["after"], title_override=input_title if draft else None)["issues"]
            fixed["remaining"] = [i for i in shared_remaining if i["code"] in selected]
            fixed["manual"] = [i for i in fixed["remaining"] if i.get("method") == "manual"]
            manual_book = [i for i in book_issues if i["code"] in selected and (i["index"] == base["index"] or base["index"] in i.get("related_indexes", []))]
            fixed["manual"].extend(manual_book)
            fixed["remaining"].extend(manual_book)
            result.update(after=fixed["after"], before=text, title=input_title, changes=fixed["changes"], remaining=fixed["remaining"], draft=draft)
            before_issues = validation.chapter_validation_report(ch, storage, publication, text_override=text, title_override=input_title if draft else None)["issues"] + manual_book
            result["counts"] = {code: {"before": sum(i["code"] == code for i in before_issues), "after_algorithm": sum(i["code"] == code for i in fixed["remaining"])} for code in codes}
            changed = fixed["after"] != text
            record("THUẬT TOÁN", f"{'có đổi' if changed else 'không đổi'}; " + "; ".join(f"{code}={count['before']}→{count['after_algorithm']}" for code, count in result["counts"].items()))
            if not draft and fixed["after"] != text:
                commit = _commit(storage, base, fixed["after"], base["title"], f"proofreading-run:{storage.slug}:{run_id}:{base['index']}" if run_id else str(uuid4()), codes=codes)
                result["committed"] = True
                record("ĐÃ GHI", f"nhánh={base['branch']}; revision={base['revision']}→{commit.document.revision}; history canonical; không rebuild/publish")
                record("LỖI DB", "đã kiểm tra lại chapter bằng logic Build EPUB và lưu lỗi còn lại trong cùng transaction")
                # Không đổi sang publication mới nếu writer khác chạy ngay sau commit.
                base = check_snapshot(storage, {**base, "revision": commit.document.revision, "hash": full_content_hash(base["title"], fixed["after"])})
            elif draft:
                record("DRAFT", "chỉ trả kết quả vào draft, chưa ghi DB; Lưu mới ghi")
            else:
                record("KHÔNG GHI", "thuật toán không đổi nội dung")
                from .content_validation import refresh_chapter
                refresh_chapter(storage, base["index"])
                check_snapshot(storage, base)
                record("LỖI DB", "đã kiểm tra và làm mới lỗi của chapter; không ghi nội dung hoặc tăng revision")
            result["base"] = base
            text = fixed["after"]
            spans = evidence_spans(text, selected)
            whole = bool(fixed["manual"] and len(instructions.strip()) >= 20)
            if not spans and not whole:
                result["unresolved"] = "Không có bằng chứng AI trong mã đã chọn; lỗi manual/informational cần kiểm tra tay." if fixed["remaining"] else ""
                record("AI BỎ QUA", result["unresolved"] or "không còn bằng chứng lỗi trong mã đã chọn")
                continue
            if not cfg.ai.openai.base_url or not cfg.ai.openai.model:
                result["unresolved"] = "Chưa cấu hình ai.openai hiệu lực; đã giữ kết quả thuật toán/draft."
                record("AI BỎ QUA", result["unresolved"])
                continue
            try:
                record("AI", f"tạo đề xuất; {len(spans)} vùng bằng chứng; chưa ghi kết quả AI")
                raw = storage.read_raw(storage.get_chapter(base["index"]))
                response = (call_ai or openai_client.run_chat)(cfg.ai.openai, build_prompt(text, input_title, raw, spans, instructions, whole))
                proposed = validate_ai_edits(text, response, spans, title=input_title, whole=whole)
                check_snapshot(storage, base)  # AI chạy xong phải còn đúng nguồn publication.
                payload = {**proposed, "before": text, "before_title": input_title, "base": base, "draft": draft, "draft_hash": full_content_hash(input_title, text), "codes": codes, "instructions": instructions, "spans": spans, "whole": whole, "model": cfg.ai.openai.model, "engine": "proofreading", "prompt_version": 1}
                candidate = revisions.create_revision(engine="proofreading", idx=base["index"], payload=json.dumps(payload, ensure_ascii=False), base_translated_text=text, base_rev=base["revision"], has_raw=bool(raw), branch=base["branch"])
                result["candidate_id"] = storage.create_ai_revision(candidate)
                result["candidate"] = payload
                record("CHỜ DUYỆT", f"candidate={result['candidate_id']}; {len(proposed['edits'])} edit; đọc FULL diff và duyệt toàn chương")
            except Exception:
                # Không echo HTTP/provider exceptions: có thể chứa secret/prompt.
                result["unresolved"] = "AI thất bại/kết quả sai hoặc stale; giữ thuật toán/draft, cần tạo lại."
                record("AI KHÔNG ÁP", result["unresolved"])
        except Exception as exc:
            result["error"] = str(exc) if isinstance(exc, (ProofreadingError, ValueError)) or hasattr(exc, "code") else "Không xử lý được chương; giữ dữ liệu, kiểm tra history/baseline."
            record("TỪ CHỐI/LỖI", result["error"] + ("; đã giữ commit thuật toán trước đó" if result.get("committed") else "; không ghi đè"))
        finally:
            record("KẾT THÚC", f"đã ghi thuật toán={bool(result.get('committed'))}; draft={bool(result.get('draft'))}; candidate={result.get('candidate_id') or '-'}; còn cần kiểm tra={bool(result.get('error') or result.get('unresolved') or result.get('candidate_id') or result.get('draft'))}")
            results.append(result)
    log(f"[proofreading] TỔNG KẾT: {len(results)} chương; {sum(bool(r.get('committed')) for r in results)} đã ghi; {sum(bool(r.get('candidate_id')) for r in results)} chờ duyệt; {sum(bool(r.get('error')) for r in results)} lỗi/xung đột; {sum(bool(r.get('unresolved')) for r in results)} chưa giải quyết")
    return {"chapters": results}


def candidate_view(storage, index: int, candidate_id: int) -> dict:
    ch = storage.get_chapter(index)
    cand = storage.read_ai_revision(ch, candidate_id) if ch else None
    if cand is None or cand.engine != "proofreading":
        raise ProofreadingError("Không có candidate soát lỗi.")
    return {"id": candidate_id, "index": index, "status": cand.status, "expires_at": cand.expires_at, **json.loads(cand.payload)}


def decide(storage, items: list[dict], *, discard=False) -> dict:
    results = []
    for item in items:
        result = {"index": item.get("index"), "id": item.get("id"), "audit": []}
        try:
            view = candidate_view(storage, item["index"], item["id"])
            result["codes"] = view["codes"]
            result["audit"].append(f"Chương {item['index']} | mã={','.join(view['codes'])} | candidate={item['id']} | nhánh={view['base']['branch']} | revision nguồn={view['base']['revision']}")
            ch = storage.get_chapter(item["index"])
            cand = storage.read_ai_revision(ch, item["id"])
            if discard:
                if cand.status != "pending":
                    raise ProofreadingError("Candidate không còn pending.")
                storage.mark_ai_revision(ch, item["id"], status="discarded")
                result["audit"].append("ĐÃ BỎ đề xuất; không ghi nội dung chương.")
            else:
                base = check_snapshot(storage, view["base"])
                text = item.get("draft_text") if view["draft"] else base["text"]
                if view["draft"] and full_content_hash(item.get("draft_title", view["before_title"]), text or "") != view["draft_hash"]:
                    raise ProofreadingError("Draft đã đổi khi AI chạy — tạo lại, không overwrite.")
                reason = revisions.check_still_valid(cand, current_rev=base["revision"], current_translated_text=text)
                if reason:
                    raise ProofreadingError(reason)
                # Không tin payload do UI gửi; kiểm chứng lại offsets stored candidate.
                proposal = validate_ai_edits(text, {"edits": view["edits"], "title": view["title"]}, view["spans"], title=view["before_title"], whole=view["whole"])
                if view["draft"]:
                    storage.mark_ai_revision(ch, item["id"], status="applied")
                    result.update(draft=True, after=proposal["after"], title=proposal["title"])
                    result["audit"].append("ĐÃ DUYỆT vào draft; chưa ghi nội dung DB, Lưu mới ghi.")
                else:
                    commit = _commit(storage, base, proposal["after"], proposal["title"], f"proofreading-apply:{storage.slug}:{item['id']}", item["id"], codes=view["codes"])
                    result["document"] = asdict(commit.document)
                    result["audit"].append(f"ĐÃ ÁP AI vào {base['branch']} | revision={base['revision']}→{commit.document.revision} | hash={commit.document.content_hash} | history canonical")
                    result["audit"].append("Đã cập nhật lỗi còn lại trong SQLite bằng cùng kiểm tra trước Build EPUB.")
            result["ok"] = True
        except Exception as exc:
            result.update(ok=False, error=str(exc) if isinstance(exc, (ProofreadingError, ValueError)) or hasattr(exc, "code") else "Không áp dụng được candidate; giữ dữ liệu.")
            result["audit"].append("TỪ CHỐI/KHÔNG ÁP: " + result["error"])
        try:
            storage.write_extra_json(f"proofreading_decision:{item.get('index')}:{item.get('id')}", {k: v for k, v in result.items() if k not in {"document", "after", "title"}})
        except Exception:
            result["audit"].append("Không lưu được log phụ của quyết định; đối chiếu canonical history/status candidate, không tự chạy lại.")
        results.append(result)
    return {"chapters": results}
