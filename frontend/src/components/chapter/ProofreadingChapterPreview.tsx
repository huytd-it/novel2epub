import { useEffect, useState } from "react";
import { proofreadingApi, useSaveChapterText, type ProofreadingSnapshot } from "@/lib/chapter";
import { VALIDATION_CONTRACT } from "@/lib/validation";
import { Modal, ConfirmDialog } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { Loading } from "@/components/ui/Loading";

/** Preview đúng publication, sửa tay toàn văn với revision/hash/publication CAS. */
export function ProofreadingChapterPreview({ slug, index, onClose, onSaved }: {
  slug: string; index: number; onClose: () => void; onSaved: () => void;
}) {
  const [base, setBase] = useState<ProofreadingSnapshot | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [discard, setDiscard] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const save = useSaveChapterText(slug, index);
  useEffect(() => {
    let cancelled = false;
    void proofreadingApi.analyze(slug, [index], [], {}).then(report => {
      if (cancelled) return;
      const row = report.chapters[0];
      if (!row || row.error) throw new Error(row?.error || "Không có nguồn chương để preview.");
      setBase(row); setText(row.text); setTitle(row.title);
      setLogs([`PREVIEW chương ${index} | nhánh=${row.branch} | revision=${row.revision} | hash=${row.hash} | ${row.issues?.length ?? 0} cảnh báo`]);
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, index]);
  const dirty = Boolean(base && (base.text !== text || base.title !== title));
  const close = () => { if (save.isPending) return; if (dirty) setDiscard(true); else onClose(); };
  const saveManual = async () => {
    if (!base) return;
    setError("");
    try {
      const result = await save.mutateAsync({ translated: text, title, expectedRev: base.revision, expectedHash: base.hash, branch: base.branch, publicationBranch: base.branch, publicationTitle: base.display_title, proofreadingCodes: [...new Set((base.issues ?? []).map(i => i.code))] });
      setLogs(old => [...old, `ĐÃ LƯU THỦ CÔNG chương ${index} | nhánh=${base.branch} | revision=${base.revision}→${result.revision} | hash=${result.content_hash} | history canonical; lỗi còn lại đã cập nhật trong SQLite; không rebuild/publish`]);
      // Đóng editor sau ghi; không áp report cũ lên draft mới nếu request tải lỗi.
      setBase({ ...base, text, title, hash: result.content_hash, revision: result.revision, display_title: title || base.display_title });
      setEditing(false); onSaved();
      setLoading(true);
      try {
        const response = await proofreadingApi.analyze(slug, [index], [], {});
        const current = response.chapters[0];
        if (!current || current.error) throw new Error(current?.error || "Không tải được cảnh báo sau lưu.");
        setBase(current); setText(current.text); setTitle(current.title);
      } catch { setError("Đã lưu thành công nhưng chưa tải được cảnh báo mới. Đóng preview và mở lại; không Lưu lại dữ liệu cũ."); }
      finally { setLoading(false); }
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e);
      setError(`Chưa lưu: ${reason}. Giữ bản sửa tay; không ghi đè. Mở lại preview để kiểm tra nguồn.`);
      setLogs(old => [...old, `TỪ CHỐI LƯU chương ${index} | nhánh=${base.branch} | revision xác nhận=${base.revision} | ${reason}`]);
    }
  };
  return <>
    <Modal open onClose={close} title={`Preview chương ${index} · cảnh báo / sửa thủ công`} xl footer={<>
      {base && !editing && <Button disabled={loading} onClick={() => setEditing(true)}>Sửa thủ công</Button>}
      {editing && <Button variant="primary" disabled={!dirty || loading} loading={save.isPending} onClick={() => void saveManual()}>Lưu sửa thủ công</Button>}
      <Button disabled={save.isPending} onClick={close}>Đóng preview</Button>
    </>}>
      {error && <p role="alert" className="mb-3 text-sm text-error">{error}</p>}
      {loading ? <Loading label="Đang đọc chương và cảnh báo" /> : base && <div className="space-y-4 text-sm">
        <p>Nhánh <strong>{base.branch}</strong> · revision {base.revision}. Chỉnh sửa chưa ghi cho đến khi bấm Lưu.</p>
        <details open className="border-b border-base-300 pb-3"><summary className="cursor-pointer font-semibold">{base.issues?.length ?? 0} cảnh báo mới nhất</summary>
          <ul className="mt-2 max-h-56 space-y-2 overflow-auto">{(base.issues ?? []).map((issue, position) => <li key={position} className="break-words"><strong>{VALIDATION_CONTRACT.find(c => c.code === issue.code)?.label ?? issue.code}</strong>: {issue.message}{issue.paraIndex >= 0 && ` · đoạn ${issue.paraIndex + 1}`}{issue.snippet && <span className="block whitespace-pre-wrap opacity-70">{issue.snippet}</span>}</li>)}</ul>
        </details>
        {editing ? <>
          <label className="block">Tiêu đề nhánh<Input aria-label="Tiêu đề sửa thủ công" value={title} disabled={save.isPending} onChange={event => setTitle(event.target.value)} /></label>
          <label className="block">Toàn bộ nội dung<Textarea aria-label="Nội dung sửa thủ công" className="w-full font-reader" rows={20} value={text} disabled={save.isPending} onChange={event => setText(event.target.value)} /></label>
        </> : <article><h4 className="mb-3 font-semibold">{base.display_title || base.title}</h4><pre className="whitespace-pre-wrap break-words font-reader leading-relaxed">{base.text}</pre></article>}
      </div>}
      {!!logs.length && <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold">Log preview / sửa thủ công</summary><pre className="mt-2 whitespace-pre-wrap break-words text-xs">{logs.join("\n")}</pre></details>}
    </Modal>
    <ConfirmDialog open={discard} onCancel={() => setDiscard(false)} onConfirm={onClose} title="Bỏ bản sửa chưa lưu?" body="Nội dung sửa tay trong preview chưa được ghi. Đóng sẽ bỏ bản sửa này; bản lưu trong DB không đổi." confirmLabel="Bỏ bản sửa và đóng" destructive />
  </>;
}
