import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Checkbox, Input, Select } from "@/components/ui/Field";
import { pronounsApi, type PronounApplied, type PronounBranch, type PronounPreview } from "@/lib/pronouns";

/** Local extension of the ebook review tools: explicit branch, full diff,
 * protected approval, no model calls or automatic publication. */
export function PronounsDialog({ slug, selectedIndexes, availableIndexes, onClose, onCommitted }: {
  slug: string; selectedIndexes: number[]; availableIndexes: number[];
  onClose: () => void; onCommitted: () => void;
}) {
  const sorted = [...availableIndexes].sort((a, b) => a - b);
  const [branch, setBranch] = useState<PronounBranch | "">("");
  const [scope, setScope] = useState(selectedIndexes.length ? "selected" : "range");
  const [start, setStart] = useState(String(sorted[0] ?? 1));
  const [end, setEnd] = useState(String(sorted[Math.min(9, sorted.length - 1)] ?? 10));
  const [preview, setPreview] = useState<PronounPreview | null>(null);
  const [outcome, setOutcome] = useState<PronounApplied | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState("");
  const validRange = /^\d+$/.test(start) && /^\d+$/.test(end) && Number(start) <= Number(end);
  const indexes = scope === "selected" ? selectedIndexes : validRange
    ? sorted.filter(index => index >= Number(start) && index <= Number(end)) : [];
  const scopeError = scope === "range" && !validRange ? "Nhập khoảng index hợp lệ: từ không lớn hơn đến."
    : indexes.length > 50 ? "Mỗi lượt tối đa 50 chương. Hãy thu hẹp phạm vi hoặc chọn ít chương hơn."
      : !indexes.length ? "Không có chương trong phạm vi này. Chọn chương trong bảng hoặc đổi khoảng index." : "";

  const reset = () => { setPreview(null); setOutcome(null); setApproved(false); setError(""); };
  const analyze = async () => {
    if (!branch || scopeError || busy) return;
    reset(); setBusy("preview");
    try { setPreview(await pronounsApi.preview(slug, { branch, indexes })); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  const apply = async () => {
    if (!preview || !approved || busy) return;
    setBusy("apply"); setError("");
    try {
      const result = await pronounsApi.apply(slug, preview);
      setOutcome(result); setPreview(null); setApproved(false);
      onCommitted();
    } catch (e) {
      // Never offer a blind retry: a network error may follow a successful write.
      setPreview(null); setApproved(false);
      setError(`${e instanceof Error ? e.message : String(e)} Hãy xem trước lại để kiểm tra trạng thái hiện tại; không tự gửi lại lệnh ghi.`);
      onCommitted();
    } finally { setBusy(null); }
  };

  return <Modal open onClose={() => { if (!busy) onClose(); }} dismissible={!busy} title="Chuẩn hóa xưng hô" xl
    footer={<>
      <Button disabled={Boolean(busy)} onClick={onClose}>Đóng</Button>
      {preview && preview.chapters.length > 0
        ? <Button variant="primary" loading={busy === "apply"} disabled={!approved || Boolean(busy)} onClick={apply}>
          Áp dụng {preview.chapters.length} chương đã duyệt
        </Button>
        : <Button variant="primary" loading={busy === "preview"} disabled={!branch || Boolean(scopeError) || Boolean(busy)} onClick={analyze}>Xem trước thay đổi</Button>}
    </>}>
    <div className="space-y-5 text-sm">
      <div className="space-y-2">
        <p>Thống nhất lời thoại theo phong cách võ hiệp bằng quy tắc cục bộ. <strong>Không gọi AI, không tốn token.</strong></p>
        <p className="text-base-content/75"><strong>tôi / tao / tớ → ta</strong> · <strong>mày → ngươi</strong>. Giữ số nhiều, lời kể và danh xưng quan hệ. “Ngươi” không phù hợp với mọi vai vế; hãy duyệt thay đổi trước khi ghi.</p>
      </div>

      <fieldset disabled={Boolean(busy)} className="grid gap-4 border-y border-base-300 py-4 sm:grid-cols-2">
        <label className="space-y-1"><span className="block font-medium">Nhánh bản dịch</span>
          <Select className="w-full" value={branch} onChange={e => { reset(); setBranch(e.target.value as PronounBranch | ""); }}>
            <option value="">Chọn nhánh cần sửa</option><option value="ai">Bản dịch AI</option><option value="local_mt">Bản dịch Local MT</option>
          </Select>
        </label>
        <label className="space-y-1"><span className="block font-medium">Phạm vi chương</span>
          <Select className="w-full" value={scope} onChange={e => { reset(); setScope(e.target.value); }}>
            <option value="selected" disabled={!selectedIndexes.length}>Chương đã chọn trong bảng ({selectedIndexes.length})</option>
            <option value="range">Khoảng index trong kết quả đang lọc</option>
          </Select>
        </label>
        {scope === "range" && <div className="grid grid-cols-2 gap-3 sm:col-span-2">
          <label className="space-y-1"><span className="block">Từ index</span><Input className="w-full" type="number" min={0} step={1} value={start} onChange={e => { reset(); setStart(e.target.value); }} /></label>
          <label className="space-y-1"><span className="block">Đến index</span><Input className="w-full" type="number" min={0} step={1} value={end} onChange={e => { reset(); setEnd(e.target.value); }} /></label>
        </div>}
        <p className="text-base-content/75 sm:col-span-2">{scopeError || `${indexes.length} chương trong phạm vi · tối đa 50 chương mỗi lượt. Chương bỏ qua hoặc chưa dịch hoàn chỉnh sẽ không được sửa.`}</p>
      </fieldset>

      <details className="text-base-content/75"><summary className="cursor-pointer font-medium">Quy tắc và giới hạn an toàn</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Chỉ sửa lời thoại có cặp ngoặc kép trên cùng dòng; bỏ qua ngoặc lồng, ngoặc thiếu và thoại gạch đầu dòng.</li>
          <li>Không tự đổi anh/em, bạn/mình/mi, hắn/nàng hay sư phụ/đệ tử. Entity được bảo vệ và từ đồng âm thường gặp được giữ nguyên.</li>
          <li>Có thể bỏ sót hoặc nhận nhầm trích dẫn. Đây là chuẩn hóa phong cách, không phải suy luận người nói.</li>
          <li>Chỉ ghi nhánh đã chọn và lưu lịch sử phiên bản. Không thay bản gốc, snapshot MT, nhánh còn lại; không tự build EPUB hay đẩy Reader.</li>
          <li>Ghi từng chương, không phải giao dịch toàn sách. Chương ghi thành công vẫn được giữ nếu chương khác xung đột. Nên sao lưu DB trước khi sửa hàng loạt.</li>
        </ul>
      </details>

      {busy && <p role="status">{busy === "preview" ? "Đang tìm các chỗ xưng hô có thể chuẩn hóa…" : "Đang ghi các chương đã duyệt và lưu lịch sử…"}</p>}
      {error && <p role="alert" className="text-error">{error}</p>}
      {outcome && <section aria-label="Kết quả chuẩn hóa" className="space-y-2" role="status">
        <h4 className="font-semibold">Đã lưu {outcome.applied.length} chương · {outcome.replacements} chỗ xưng hô</h4>
        {!!outcome.applied.length && <p>Index đã lưu: {outcome.applied.join(", ")}. Có thể xem bản cũ trong lịch sử chương.</p>}
        {!!outcome.failed.length && <ul className="space-y-1 text-error">{outcome.failed.map(item => <li key={item.index}>Index {item.index}: {item.error}</li>)}</ul>}
        <p>Không tự build EPUB hoặc đẩy Reader. Xem trước lại nếu muốn tiếp tục.</p>
      </section>}

      {preview && <section aria-label="Bản xem trước xưng hô" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-semibold">{preview.chapters.length ? `${preview.replacements} chỗ thay trong ${preview.chapters.length} chương` : "Không tìm thấy chỗ cần chuẩn hóa bằng quy tắc hiện tại"}</h4>
          <Button size="sm" disabled={Boolean(busy)} onClick={analyze}>Xem trước lại</Button>
        </div>
        <p className="text-base-content/75">Đã quét {preview.scanned} chương · {preview.unchanged} không đổi · {preview.skipped.length} bỏ qua. Chưa có thay đổi nào được ghi.</p>
        {!preview.chapters.length && <p>Không có đề xuất không có nghĩa là xưng hô đã hoàn toàn đúng. Những đại từ mơ hồ vẫn cần đọc và biên tập theo ngữ cảnh.</p>}
        {!!preview.skipped.length && <details><summary className="cursor-pointer">Xem chương bỏ qua</summary><ul className="mt-2 space-y-1">{preview.skipped.map(item => <li key={item.index}>Index {item.index}: {item.reason}</li>)}</ul></details>}
        <div className="divide-y divide-base-300">{preview.chapters.map(chapter => <details key={chapter.index} open={preview.chapters.length === 1} className="py-3">
          <summary className="cursor-pointer break-words font-medium">Index {chapter.index} · {chapter.title || "Chưa có tiêu đề"} · {chapter.replacements} chỗ thay</summary>
          <p className="mt-2 text-xs text-base-content/75">Dòng − là bản cũ; dòng + là bản đề xuất. Hiển thị đầy đủ diff, không cắt bớt thay đổi.</p>
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-field border border-base-300 bg-base-100 p-3 font-sans text-sm leading-relaxed">{chapter.diff.split("\n").map((line, index) => <span key={index} className={line.startsWith("-") ? "text-error" : line.startsWith("+") ? "text-success" : ""}>{line}{"\n"}</span>)}</pre>
        </details>)}</div>
        {preview.chapters.length > 0 && <label className="flex items-start gap-3 border-t border-base-300 pt-4">
          <Checkbox className="mt-1 shrink-0" checked={approved} disabled={Boolean(busy)} onChange={e => setApproved(e.target.checked)} />
          <span>Tôi đã xem các thay đổi trước/sau và đồng ý áp dụng toàn bộ {preview.chapters.length} chương trong nhánh {preview.branch === "ai" ? "AI" : "Local MT"}.</span>
        </label>}
      </section>}
    </div>
  </Modal>;
}
