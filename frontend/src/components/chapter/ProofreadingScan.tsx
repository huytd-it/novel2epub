import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "@/lib/api";
import { proofreadingApi, type ProofreadingScanReport } from "@/lib/chapter";
import type { QueueSnapshot } from "@/lib/queue";
import { num } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import { VALIDATION_CONTRACT, METHOD_LABELS, supportedMethod } from "@/lib/validation";

/**
 * Quét lỗi toàn truyện rồi lọc hiển thị theo mã.
 *
 * Panel này CHỈ rà soát + liệt kê cảnh báo. Sửa lỗi làm thủ công tại trang
 * Chapter (link "Mở Chapter để sửa" mở editor kèm preview) hoặc qua nút
 * "Soát lỗi" ở thanh hàng loạt — không có fix tự động tại chỗ nên không có
 * nút chọn/fix hàng loạt ở đây.
 */
export function ProofreadingScan({ slug, codes, onCodesChange, onReport, refreshWhileFixing = false }: {
  slug: string; codes: string[]; onCodesChange: (codes: string[]) => void;
  onReport?: (report: ProofreadingScanReport | null) => void;
  refreshWhileFixing?: boolean;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [report, setReport] = useState<ProofreadingScanReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const client = useQueryClient();
  const saved = useQuery({ queryKey: ["content-validation", slug], queryFn: () => proofreadingApi.state(slug), retry: false, refetchInterval: refreshWhileFixing ? 3000 : false });
  useEffect(() => { if (saved.data) setReport(saved.data.checked || saved.data.checked_at ? saved.data : null); }, [saved.data]);
  useEffect(() => { onReport?.(report); }, [report, onReport]);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  const queue = useQuery({ queryKey: ["proofreading-scan-job", slug, jobId], queryFn: () => api.get<QueueSnapshot>("/api/queue"), enabled: Boolean(jobId) && !finished, refetchInterval: 1500 });
  useEffect(() => {
    if (!jobId || !queue.data) return;
    const jobs = [...queue.data.running, ...Object.values(queue.data.pending).flat(), ...queue.data.history];
    const job = jobs.find(j => j.id === jobId);
    if (!job || !["done", "failed", "cancelled"].includes(job.state)) return;
    setFinished(true);
    if (job.state !== "done") { setError("Rà soát thất bại/đã hủy. Xem lịch sử job và bấm rà lại khi sẵn sàng."); return; }
    const current = generation.current;
    let cancelled = false;
    void saved.refetch().then(response => {
      if (cancelled || current !== generation.current) return;
      if (response.error || !response.data) { setError("Không tải được lỗi đã lưu; không cần quét lại."); return; }
      setReport(response.data); setError("");
      // Lỗi đã lưu trong DB — bảng chương (bộ lọc proofreading_code, badge)
      // đọc từ DB nên phải tải lại, nếu không vẫn hiện số liệu cũ sau khi rà.
      client.invalidateQueries({ queryKey: ["chapters", slug] });
    });
    return () => { cancelled = true; };
  }, [jobId, queue.data, slug, client]);

  const scan = async () => {
    const current = ++generation.current;
    setBusy(true); setError(""); setReport(null);
    try {
      const response = await proofreadingApi.scan(slug);
      if (current !== generation.current) return;
      setJobId(response.job_id); setFinished(false);
    } catch (e) { if (current === generation.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (current === generation.current) setBusy(false); }
  };
  const issues = useMemo(() => report?.chapters.flatMap(row => row.issues) ?? [], [report]);
  const filterCode = codes[0] ?? "";
  const scannedCodes = [...new Set(issues.map(issue => issue.code))].sort();
  const visible = useMemo(() => (report?.chapters ?? []).map(row => ({ ...row, issues: row.issues.filter(i => !filterCode || i.code === filterCode) })).filter(row => row.issues.length > 0), [report, filterCode]);
  const pageCount = Math.max(1, Math.ceil(visible.length / 25));
  const currentPage = Math.min(page, pageCount - 1);
  useEffect(() => { setPage(0); }, [codes.join(",")]);
  const running = busy || Boolean(jobId && !finished);
  return <section aria-label="Soát lỗi hàng loạt" className="border-b border-base-300">
    <div className="flex flex-wrap items-center gap-3 px-3 py-2">
      {report ? (
        <label className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-xs">Lọc theo mã lỗi
          <Select aria-label="Lọc theo mã lỗi đã rà soát" value={filterCode} onChange={event => onCodesChange(event.target.value ? [event.target.value] : [])} className="max-w-full">
            <option value="">Tất cả mã lỗi đã rà soát</option>
            {filterCode && !scannedCodes.includes(filterCode) && <option value={filterCode}>{filterCode} · Không còn lỗi</option>}
            {scannedCodes.map(code => <option key={code} value={code}>{code} · {VALIDATION_CONTRACT.find(c => c.code === code)?.label ?? code} · {num(report.chapters.filter(row => row.issues.some(issue => issue.code === code)).length)} chương</option>)}
          </Select>
        </label>
      ) : (
        <span className="flex-1" aria-hidden="true" />
      )}
      <Button size="sm" disabled={running} onClick={() => void scan()}>{running ? "Đang rà soát…" : "Rà soát tất cả lỗi"}</Button>
    </div>
    {running && <p role="status" className="px-3 py-2 text-xs">Đang quét mọi mã lỗi và kiểm tra trùng/số chương trong một job…</p>}
    {(error || queue.error || saved.error) && <p role="alert" className="px-3 py-2 text-xs text-error">{error || "Không đọc được trạng thái/lỗi đã lưu."}</p>}
    {!report && saved.isPending && <p role="status" className="px-3 py-2 text-xs">Đang đọc lỗi đã lưu…</p>}
    {saved.data && !saved.data.checked && !running && <p className="px-3 py-2 text-xs">Chưa có lỗi được lưu. Bấm Rà soát tất cả lỗi để khởi tạo.</p>}
    {report && <>
      {report.chapters.some(row => row.stale) && <p role="status" className="px-3 py-2 text-xs text-warning">Một số chapter thay đổi ngoài luồng sửa canonical hoặc luật kiểm tra đã đổi. Rà lại để cập nhật; preview luôn đọc nguồn mới.</p>}
      {!visible.length ? <p className="px-3 py-2 text-xs">Không có lỗi khớp mã đang chọn.</p> : !onReport && <div className="overflow-x-auto">
        <table aria-label="Chapter có lỗi" className="w-full min-w-[44rem] border-collapse text-left text-xs">
          <thead><tr className="border-y border-base-300 bg-base-200/60"><th className="p-3">Chapter</th><th className="p-3">Cảnh báo / lỗi phát hiện</th><th className="p-3">Sửa</th></tr></thead>
          <tbody>{visible.slice(currentPage * 25, (currentPage + 1) * 25).map(row => <tr key={row.index} className="border-b border-base-300 align-top">
            <td className="p-3"><Link className="break-words font-semibold hover:text-primary" to={`/ebooks/${slug}/chapters/${row.index}`}>#{row.index} {row.title}</Link></td>
            <td className="p-3">
              {row.stale && <p className="mb-2 text-warning">Lỗi đã lưu có thể cũ — cần rà lại</p>}
              {row.error && <p className="text-error">{row.error}</p>}
              <ul className="space-y-2">{[...new Set(row.issues.map(issue => issue.code))].map(code => {
                const grouped = row.issues.filter(issue => issue.code === code);
                const label = VALIDATION_CONTRACT.find(c => c.code === code)?.label ?? code;
                return <li key={code}><span className="inline-flex rounded-selector bg-warning/15 px-2 py-1 font-semibold text-warning" title={code}>{label} · {grouped.length}</span><span className="ml-2 opacity-70">{METHOD_LABELS[supportedMethod(code)]}</span>
                  <details className="mt-1"><summary className="cursor-pointer">Xem cảnh báo {label}</summary><ul className="mt-1 space-y-1">{grouped.map((issue, position) => <li key={position} className="break-words">{issue.message}{issue.paraIndex >= 0 && ` · đoạn ${issue.paraIndex + 1}`}{issue.snippet && <span className="block whitespace-pre-wrap opacity-70">{issue.snippet}</span>}</li>)}</ul></details>
                </li>;
              })}</ul>
            </td>
            <td className="p-3"><Link className="btn btn-sm btn-ghost" to={`/ebooks/${encodeURIComponent(slug)}/chapters/${row.index}?edit=1`} aria-label={`Mở Chapter để sửa chương ${row.index}`}>Mở Chapter để sửa</Link></td>
          </tr>)}</tbody>
        </table>
      </div>}
      {!onReport && pageCount > 1 && <div className="flex items-center justify-end gap-2 px-3 py-2 text-xs">
        <span>Trang lỗi {currentPage + 1}/{pageCount} · 25 chương/trang</span>
        <Button size="sm" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Lỗi trang trước</Button>
        <Button size="sm" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>Lỗi trang sau</Button>
      </div>}
    </>}
  </section>;
}
