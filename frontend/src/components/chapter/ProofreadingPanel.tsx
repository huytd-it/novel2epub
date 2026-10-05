import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { proofreadingApi, type ProofreadingCandidate, type ProofreadingResult, type ProofreadingSnapshot } from "@/lib/chapter";
import type { QueueSnapshot } from "@/lib/queue";
import { VALIDATION_CONTRACT, METHOD_LABELS, type ValidationIssue } from "@/lib/validation";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";

export interface ProofreadingDraft {
  slug: string; index: number; text: string; title: string; branch: string; revision: number; editing: boolean; generation: number;
}

export function sameProofreadingDraft(a: ProofreadingDraft, b: ProofreadingDraft): boolean {
  return a.slug === b.slug && a.index === b.index && a.branch === b.branch && a.revision === b.revision && a.generation === b.generation && a.text === b.text && a.title === b.title && a.editing === b.editing;
}

/** Tìm nhiều mã bằng các checkbox native: Tab/Space, nhãn và đếm đầy đủ. */
export function ProofreadingCodes({ codes, onChange, issues, scope = "chapter" }: { codes: string[]; onChange: (codes: string[]) => void; issues?: ValidationIssue[]; scope?: "chapter" | "book" }) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const options = VALIDATION_CONTRACT.filter(c => `${c.label} ${c.code}`.toLocaleLowerCase("vi").includes(query.toLocaleLowerCase("vi")));
  return <details ref={detailsRef} className="border-b border-base-300 p-3" onToggle={e => setExpanded(e.currentTarget.open)}>
    <summary className="cursor-pointer text-sm font-medium">Mã lỗi: {codes.length ? `${codes.length} loại đã chọn` : "Tất cả (chưa chọn để sửa)"}</summary>
    <label className="mt-2 block text-xs">Tìm mã lỗi
      <input className="input input-sm mt-1 w-full" role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={listId} value={query} onChange={e => setQuery(e.target.value)} placeholder="Tiếng Việt hoặc mã lỗi" onKeyDown={e => {
        if (e.key === "ArrowDown") { e.preventDefault(); document.getElementById(listId)?.querySelector<HTMLInputElement>("input")?.focus(); }
        if (e.key === "Escape" && detailsRef.current) { detailsRef.current.open = false; detailsRef.current.querySelector("summary")?.focus(); }
      }} />
    </label>
    <p className="mt-2 text-xs opacity-70">{issues ? scope === "book" ? "Số lần trong báo cáo toàn sách. Chọn mã để lọc cảnh báo hiển thị; chọn một loại lỗi riêng khi fix hàng loạt." : "Số lần trong chương đang mở." : "Mã áp dụng khi phân tích các chương đã chọn; không lọc bảng chương."} {scope === "book" ? "Không chọn mã lọc: hiện tất cả chapter có lỗi." : "Không chọn mã: hiện tất cả, chặn sửa."}</p>
    <fieldset id={listId} role="listbox" aria-label="Chọn nhiều mã lỗi" aria-multiselectable="true" className="mt-2 max-h-64 overflow-y-auto" onKeyDown={e => {
      const inputs = Array.from(e.currentTarget.querySelectorAll<HTMLInputElement>("input"));
      const position = inputs.indexOf(document.activeElement as HTMLInputElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); inputs[(position + (e.key === "ArrowDown" ? 1 : -1) + inputs.length) % inputs.length]?.focus(); }
      if (e.key === "Escape" && detailsRef.current) { detailsRef.current.open = false; detailsRef.current.querySelector("summary")?.focus(); }
    }}>
      <legend className="sr-only">Chọn nhiều loại lỗi để lọc và sửa</legend>
      {!options.length && <p className="py-2 text-xs">Không có mã khớp.</p>}
      {options.map(c => <label key={c.code} role="option" aria-selected={codes.includes(c.code)} className="flex cursor-pointer items-start gap-2 py-2 text-xs">
        <input type="checkbox" className="checkbox checkbox-sm" checked={codes.includes(c.code)} onChange={e => onChange(e.target.checked ? [...codes, c.code] : codes.filter(v => v !== c.code))} />
        <span>{c.label}{issues && ` (${issues.filter(i => i.code === c.code).length})`}<span className="block opacity-70">{METHOD_LABELS[c.method]} · {c.code}</span></span>
      </label>)}
    </fieldset>
    <button type="button" className="btn btn-ghost btn-xs mt-2" onClick={() => onChange([])}>Bỏ chọn mã</button>
  </details>;
}

/** Full document diff từ edits đã xác minh, O(n), không dùng word-LCS cả chương. */
export function ProofreadingDiff({ candidate, before }: { candidate: ProofreadingCandidate; before: string }) {
  const chunks = useMemo(() => {
    const codepoints = Array.from(before);
    const parts: { before: string; after: string; changed: boolean }[] = [];
    let cursor = 0;
    for (const e of candidate.edits) {
      parts.push({ before: codepoints.slice(cursor, e.start).join(""), after: codepoints.slice(cursor, e.start).join(""), changed: false });
      parts.push({ before: e.original, after: e.replacement, changed: true });
      cursor = e.end;
    }
    const rest = codepoints.slice(cursor).join("");
    parts.push({ before: rest, after: rest, changed: false });
    return parts;
  }, [before, candidate.edits]);
  return <div className="grid gap-3 md:grid-cols-2">
    {(["before", "after"] as const).map(side => <section key={side} className="min-w-0">
      <h4 className="mb-2 font-semibold">{side === "before" ? "Trước" : "Đề xuất AI"}</h4>
      <p className="mb-2 whitespace-pre-wrap break-words font-semibold">{side === "before" ? candidate.before_title ?? candidate.base.title : candidate.title}</p>
      <pre className="whitespace-pre-wrap break-words font-reader text-sm leading-relaxed">{chunks.map((p, i) => p.changed ? <mark key={i} className={side === "before" ? "bg-error/20 text-base-content" : "bg-success/20 text-base-content"}>{p[side]}</mark> : <span key={i}>{p[side]}</span>)}</pre>
    </section>)}
  </div>;
}

export function ProofreadingPanel({ open, onClose, slug, indexes, codes, getDraft, applyDraft, onCommitted, pendingCandidates, onGoto, singleCode = false, onCodeChange, onJobStateChange }: {
  open: boolean; onClose: () => void; slug: string; indexes: number[]; codes: string[];
  getDraft: () => ProofreadingDraft;
  applyDraft: (expected: ProofreadingDraft, after: string, title?: string) => boolean;
  onCommitted: (results?: ProofreadingResult[]) => void;
  pendingCandidates: { index: number; id: number }[];
  onGoto: (index: number) => void;
  singleCode?: boolean; onCodeChange?: (code: string) => void;
  onJobStateChange?: (running: boolean) => void;
}) {
  const [preview, setPreview] = useState<ProofreadingSnapshot[]>([]);
  const [confirmationToken, setConfirmationToken] = useState("");
  const [results, setResults] = useState<ProofreadingResult[]>([]);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [bookJob, setBookJob] = useState<string | null>(null);
  const [bookIssues, setBookIssues] = useState<{ index: number; message: string; code: string }[] | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const draftAtStart = useRef<ProofreadingDraft | null>(null);
  const previewDraft = useRef<ProofreadingDraft | null>(null);
  const handled = useRef(new Set<string>());
  const draftResultStates = useRef(new Map<string, boolean>());
  const currentSlug = useRef(slug);
  currentSlug.current = slug;
  const currentJobs = useRef({ jobId, bookJob });
  currentJobs.current = { jobId, bookJob };
  const [decision, setDecision] = useState<string[]>([]);
  const queue = useQuery({ queryKey: ["proofreading-jobs", slug, jobId, bookJob], queryFn: () => api.get<QueueSnapshot>("/api/queue"), enabled: Boolean(jobId || bookJob), refetchInterval: q => {
    const jobs = q.state.data ? [...q.state.data.running, ...Object.values(q.state.data.pending).flat(), ...q.state.data.history] : [];
    return [jobId, bookJob].some(id => id && !jobs.some(j => j.id === id && ["done", "failed", "cancelled"].includes(j.state))) ? 1500 : false;
  } });

  useEffect(() => {
    setPreview([]); setResults([]); setError(""); setChosen(new Set()); setDecision([]); setBookIssues(null); setJobId(null); setBookJob(null);
    handled.current.clear();
    draftResultStates.current.clear();
  }, [slug]);
  useEffect(() => { setPreview([]); }, [indexes.join(","), codes.join(",")]);

  useEffect(() => {
    if (!queue.data) return;
    const jobs = [...queue.data.running, ...Object.values(queue.data.pending).flat(), ...queue.data.history];
    for (const id of [jobId, bookJob]) {
      const job = jobs.find(j => j.id === id);
      if (!job || !["done", "failed", "cancelled"].includes(job.state) || handled.current.has(job.id)) continue;
      handled.current.add(job.id);
      if (job.state !== "done") { setError("Job thất bại/đã hủy. Kết quả đã ghi được giữ; kiểm tra lịch sử trước khi tạo lại."); continue; }
      const reportId = (job.outcome as { proofreading_report_id?: string })?.proofreading_report_id;
      if (!reportId) { setError("Job chưa có reference báo cáo; kiểm tra lịch sử, không tự chạy lại."); continue; }
      const load = async () => {
        const report = await proofreadingApi.result(slug, reportId);
        if (currentSlug.current !== slug || (id === bookJob ? currentJobs.current.bookJob : currentJobs.current.jobId) !== id) return;
        if (id === bookJob) { setBookIssues(report.issues ?? []); return; }
        const outcome = report.chapters ?? [];
        for (const row of outcome) {
          if (row.draft && row.after !== undefined && draftAtStart.current) {
            const key = `${job.id}:${row.index}`;
            if (!draftResultStates.current.has(key)) {
              const valid = row.before === draftAtStart.current.text && applyDraft(draftAtStart.current, row.after, row.title);
              draftResultStates.current.set(key, valid);
              if (valid) draftAtStart.current = getDraft();
            }
            if (!draftResultStates.current.get(key)) {
              row.error = "Draft/chương/nhánh đã đổi khi job chạy; không áp kết quả cũ. Hãy tạo lại.";
              row.candidate_id = null;
            }
          }
        }
        setResults(outcome); setPreview([]); setChosen(new Set()); onCommitted(outcome);
      };
      void load().catch(() => {
        if (currentSlug.current === slug && (id === bookJob ? currentJobs.current.bookJob : currentJobs.current.jobId) === id) setError("Không tải được báo cáo — bấm Tải lại kết quả; không cần chạy model lại.");
      });
    }
  }, [queue.data, jobId, bookJob, slug, applyDraft, getDraft, onCommitted]);

  const analyze = async () => {
    setBusy(true); setError(""); setDecision([]);
    try {
      const current = getDraft();
      previewDraft.current = current;
      const drafts = current.editing && indexes.includes(current.index) ? { [current.index]: { text: current.text, title: current.title, branch: current.branch, revision: current.revision } } : {};
      const response = await proofreadingApi.analyze(slug, indexes, codes, drafts);
      setPreview(response.chapters);
      setConfirmationToken(response.token);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const run = async () => {
    setBusy(true); setError("");
    try {
      const current = getDraft();
      if (singleCode && (codes.length !== 1 || VALIDATION_CONTRACT.find(c => c.code === codes[0])?.method === "informational")) throw new Error("Chọn đúng một loại lỗi có thể sửa; lỗi chỉ đánh dấu cần preview/sửa thủ công.");
      if (!previewDraft.current || !sameProofreadingDraft(previewDraft.current, current)) throw new Error("Draft đã đổi sau phân tích — phân tích lại trước khi xác nhận.");
      // Nếu vừa bật sửa trong khi đang xác nhận, không cho DB write vào chương hiện tại.
      if (current.editing && indexes.includes(current.index) && !preview.some(c => c.index === current.index && c.draft)) throw new Error("Đã mở bản sửa tay — phân tích lại để bảo vệ draft.");
      draftAtStart.current = current;
      const response = await proofreadingApi.run(slug, preview.filter(c => !c.error), codes, instructions, confirmationToken);
      setResults([]); setJobId(response.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const book = async () => {
    setBusy(true); setError("");
    try { setBookJob((await proofreadingApi.book(slug)).job_id); setBookIssues(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const loadPending = async () => {
    setBusy(true); setError("");
    try {
      const rows = await Promise.all(pendingCandidates.map(async item => {
        const candidate = await proofreadingApi.candidate(slug, item.index, item.id);
        return { index: item.index, candidate_id: item.id, candidate, base: candidate.base, before: candidate.before, after: candidate.before, title: candidate.base.title, draft: candidate.draft };
      }));
      setResults(rows); setChosen(new Set());
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const decide = async (action: "apply" | "discard") => {
    setBusy(true); setError("");
    try {
      const draft = getDraft();
      const rows = results.filter(r => r.candidate_id && chosen.has(r.candidate_id));
      for (const row of rows) if (action === "apply" && row.draft && (!draftAtStart.current || !sameProofreadingDraft(draft, draftAtStart.current) || draft.index !== row.index || draft.text !== row.after)) throw new Error("Draft đã thay đổi hoặc candidate từ lần mở cũ — không áp, hãy tạo lại.");
      const response = await proofreadingApi.decide(slug, rows.map(r => ({ index: r.index, id: r.candidate_id!, draft_text: r.draft ? draft.text : undefined, draft_title: r.draft ? draft.title : undefined })), action);
      for (const item of response.chapters) {
        if (item.ok && item.draft && item.after !== undefined && !applyDraft(draft, item.after, item.title)) item.error = "Draft đổi trong lúc duyệt — chưa áp vào editor, cần tạo lại.";
      }
      setDecision(response.chapters.map(i => `Chương ${i.index}: ${i.error || (i.ok ? action === "apply" ? "Đã duyệt toàn chương" : "Đã bỏ đề xuất" : "Không áp dụng")}\n${i.audit?.join("\n") ?? ""}`));
      setResults(old => old.filter(r => !response.chapters.some(i => i.ok && i.id === r.candidate_id)));
      setChosen(new Set()); onCommitted();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const jobs = queue.data ? [...queue.data.running, ...Object.values(queue.data.pending).flat(), ...queue.data.history] : [];
  const running = Boolean(jobId && !jobs.some(j => j.id === jobId && ["done", "failed", "cancelled"].includes(j.state)));
  useEffect(() => { onJobStateChange?.(running); }, [running, onJobStateChange]);
  return <Modal open={open} onClose={onClose} title="Soát lỗi chương / hàng loạt" xl>
    <div className="space-y-4 text-sm">
      <p>Phạm vi: <strong>{indexes.length} chương</strong> · {indexes.join(", ") || "Chưa chọn chương"}. Nguồn: AI hoàn chỉnh → Local MT, không theo nhánh đang xem.</p>
      <p>Mã đã chọn: {codes.map(c => VALIDATION_CONTRACT.find(v => v.code === c)?.label ?? c).join(", ") || "Chưa chọn mã — chỉ phân tích, không sửa"}.</p>
      {singleCode && <label className="block">Loại lỗi cho lần fix này (chỉ một loại)
        <select className="select mt-1 w-full" aria-label="Loại lỗi cho lần fix này" value={codes.length === 1 ? codes[0] : ""} disabled={busy || running} onChange={event => onCodeChange?.(event.target.value)}>
          <option value="">Chọn một loại lỗi</option>{VALIDATION_CONTRACT.map(code => <option key={code.code} value={code.code} disabled={code.method === "informational"}>{code.label} · {METHOD_LABELS[code.method]}</option>)}
        </select>
      </label>}
      <label className="block">Hướng dẫn chi tiết cho lỗi toàn chương/tiêu đề (tối thiểu 20 ký tự; không suy đoán khôi phục thiếu)
        <textarea className="textarea mt-1 w-full" rows={3} value={instructions} disabled={busy || running} onChange={e => setInstructions(e.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button disabled={!indexes.length || busy || running} onClick={analyze}>Phân tích tập đã chọn</Button>
        <Button disabled={busy || running} onClick={book}>Kiểm tra trùng/số chương toàn sách</Button>
        {pendingCandidates.length > 0 && <Button disabled={busy || running} onClick={loadPending}>Mở {pendingCandidates.length} đề xuất pending chương này</Button>}
        {(jobId || bookJob) && <Button disabled={busy} onClick={() => { if (jobId) handled.current.delete(jobId); if (bookJob) handled.current.delete(bookJob); void queue.refetch(); }}>Tải lại kết quả</Button>}
      </div>
      {busy && <p role="status">Đang xử lý…</p>}
      {(error || queue.error) && <p role="alert" className="text-error">{error || "Không tải được trạng thái job — thử mở lại, không tự chạy lại."}</p>}
      {running && <p role="status">Thuật toán → phân tích lại → AI đề xuất. Có thể đóng để tiếp tục sửa; draft thay đổi sẽ làm kết quả cũ bị từ chối.</p>}
      {!!preview.length && <section className="space-y-2">
        <h4 className="font-semibold">Xác nhận trước khi sửa {preview.filter(c => !c.error).length} chương</h4>
        <p>Thuật toán được ghi ngay sau xác nhận (nếu không có draft). AI chỉ là đề xuất cần duyệt toàn chương; AI lỗi không rollback thuật toán.</p>
        <ul className="max-h-60 overflow-auto divide-y divide-base-300">{preview.map(c => <li key={c.index} className="py-2 break-words">Chương {c.index}: {c.error || `${c.branch} · revision ${c.revision} · ${c.issues?.length ?? 0} vấn đề${c.draft ? " · chỉ sửa draft, Lưu mới ghi" : ""}`}<small className="block">{c.hash}</small></li>)}</ul>
        <Button variant="primary" disabled={!codes.length || singleCode && (codes.length !== 1 || VALIDATION_CONTRACT.find(c => c.code === codes[0])?.method === "informational") || !preview.some(c => !c.error) || busy || running} onClick={run}>Xác nhận thuật toán → đề xuất AI</Button>
      </section>}
      {bookIssues && <section><h4 className="font-semibold">Báo cáo toàn sách</h4>{!bookIssues.length ? <p>Không phát hiện trùng chính xác hoặc bất thường số chương.</p> : <ul>{bookIssues.filter(i => !codes.length || codes.includes(i.code)).map((i, n) => <li key={n}><button type="button" className="btn btn-ghost btn-sm h-auto whitespace-normal text-left" onClick={() => { onClose(); onGoto(i.index); }}>Chương {i.index}: {i.message}</button></li>)}</ul>}</section>}
      {results.map(r => <section key={r.index} className="border-t border-base-300 pt-4">
        <h4 className="font-semibold">Chương {r.index} · {r.base?.branch} {r.draft ? "· Draft chưa lưu" : r.committed ? "· Đã giữ sửa thuật toán" : ""}</h4>
        {r.error && <p role="alert" className="text-error">{r.error}</p>}
        {r.unresolved && <p className="text-warning">{r.unresolved}</p>}
        {r.audit && <details><summary className="cursor-pointer font-semibold">Log xử lý chương {r.index}</summary><pre className="mt-2 whitespace-pre-wrap break-words text-xs">{r.audit.join("\n")}</pre></details>}
        {r.candidate && r.candidate_id ? <>
          <label className="my-3 flex items-center gap-2"><input type="checkbox" className="checkbox checkbox-sm" checked={chosen.has(r.candidate_id)} onChange={e => setChosen(old => { const next = new Set(old); if (e.target.checked) next.add(r.candidate_id!); else next.delete(r.candidate_id!); return next; })} />Tôi đã xem FULL diff và duyệt toàn bộ chương {r.index}</label>
          <ProofreadingDiff candidate={r.candidate} before={r.after} />
        </> : !r.error && <p>Không có đề xuất AI cần duyệt.</p>}
      </section>)}
      {results.some(r => r.candidate_id) && <div className="flex flex-wrap gap-2 border-t border-base-300 pt-3"><Button variant="primary" disabled={busy || !chosen.size} onClick={() => decide("apply")}>Áp dụng {chosen.size} chương đã duyệt</Button><Button disabled={busy || !chosen.size} onClick={() => decide("discard")}>Bỏ {chosen.size} đề xuất</Button></div>}
      {!!decision.length && <ul aria-live="polite">{decision.map((s, i) => <li key={i} className="whitespace-pre-wrap break-words">{s}</li>)}</ul>}
      {jobId && <a className="link text-xs" href="/queue">Xem log job {jobId} trong hàng đợi</a>}
    </div>
  </Modal>;
}
