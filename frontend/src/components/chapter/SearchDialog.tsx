import { useState } from "react";

import { applyBookReplace, previewBookReplace, useBookSearch, type FindReplacePreviewItem } from "@/lib/chapter";
import { num } from "@/lib/format";
import { Modal } from "@/components/ui/Modal";
import { Button, Spinner } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { Checkbox, InputWithIcon } from "@/components/ui/Field";
import { IconSearch } from "@/components/icons";

export function SearchDialog({
  open,
  onClose,
  slug,
  onJump,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  onJump: (index: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [replacement, setReplacement] = useState("");
  const [preview, setPreview] = useState<FindReplacePreviewItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const toast = useToast();

  const { data, isFetching, error } = useBookSearch(slug, submitted, regex, caseSensitive);
  const keyOf = (item: FindReplacePreviewItem) => `${item.chapter_index}:${item.para_index}`;

  const runPreview = async () => {
    if (!query.trim()) return;
    setPreviewing(true);
    try {
      const result = await previewBookReplace(slug, query, replacement, regex);
      setPreview(result.items);
      setSelected(new Set(result.items.map(keyOf)));
      if (result.truncated) toast("Preview giới hạn 300 đoạn; hãy thu hẹp chuỗi tìm.", "error");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPreviewing(false);
    }
  };

  const applyPreview = async () => {
    const items = preview.filter((item) => selected.has(keyOf(item)));
    if (!items.length) return;
    setApplying(true);
    try {
      const result = await applyBookReplace(slug, query, replacement, regex, items);
      toast(`Đã thay ${result.replaced} chỗ trong ${result.chapters} chương${result.stale ? `; bỏ qua ${result.stale} đoạn đã đổi` : ""}.`);
      setPreview([]);
      setSubmitted(query);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setApplying(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Tìm trong toàn bộ chương đã dịch" wide>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
        className="flex flex-wrap items-center gap-3"
      >
        <InputWithIcon
          icon={<IconSearch size={14} />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Chuỗi cần tìm"
          className="min-w-[14rem] flex-1"
          autoFocus
        />
        <input className="input input-sm min-w-[12rem] flex-1" value={replacement} onChange={(e) => setReplacement(e.target.value)} placeholder="Thay bằng (có thể để trống)" />
        <label className="flex items-center gap-1.5 text-[13px] opacity-70">
          <Checkbox checked={regex} onChange={(e) => setRegex(e.target.checked)} /> Regex
        </label>
        <label className="flex items-center gap-1.5 text-[13px] opacity-70">
          <Checkbox checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />{" "}
          Hoa/thường
        </label>
        <button type="submit" className="btn btn-sm btn-primary">Tìm</button>
        <Button size="sm" loading={previewing} onClick={runPreview}>Xem trước thay thế</Button>
      </form>

      {preview.length ? (
        <div className="mt-3 border-t border-base-300 pt-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs">{selected.size}/{preview.length} đoạn được chọn</span>
            <div className="flex gap-1">
              <Button size="sm" onClick={() => setSelected(new Set(preview.map(keyOf)))}>Chọn tất cả</Button>
              <Button size="sm" onClick={() => setSelected(new Set())}>Bỏ chọn</Button>
              <Button size="sm" variant="primary" loading={applying} disabled={!selected.size} onClick={applyPreview}>Áp dụng đã chọn</Button>
            </div>
          </div>
          <div className="scroll-slim max-h-[42vh] space-y-2 overflow-y-auto">
            {preview.map((item) => {
              const key = keyOf(item);
              return (
                <label key={key} className="flex cursor-pointer gap-2 rounded-field border border-base-300 p-2 hover:bg-base-200">
                  <Checkbox checked={selected.has(key)} onChange={(e) => setSelected((current) => {
                    const next = new Set(current);
                    if (e.target.checked) next.add(key); else next.delete(key);
                    return next;
                  })} />
                  <span className="min-w-0 text-xs">
                    <strong>{item.chapter_title} · đoạn {item.para_index + 1} · {item.count} chỗ</strong>
                    <span className="mt-1 block break-words opacity-60">{item.before}</span>
                    <span className="mt-1 block break-words text-success">{item.after}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="scroll-slim mt-3 max-h-[55vh] overflow-y-auto">
        {isFetching ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : error ? (
          <p className="py-4 text-center text-xs text-error">
            {error instanceof Error ? error.message : String(error)}
          </p>
        ) : !submitted ? (
          <p className="py-8 text-center text-xs opacity-50">
            Nhập chuỗi cần tìm rồi bấm Tìm hoặc Enter.
          </p>
        ) : data && data.length === 0 ? (
          <p className="py-8 text-center text-xs opacity-50">Không tìm thấy kết quả nào.</p>
        ) : (
          <ul className="space-y-1">
            {(data ?? []).map((hit) => (
              <li key={hit.chapter_index}>
                <button
                  type="button"
                  onClick={() => {
                    onJump(hit.chapter_index);
                    onClose();
                  }}
                  className="w-full rounded-field px-2.5 py-2 text-left hover:bg-base-200"
                >
                  <span className="text-[13px] font-medium">
                    {hit.title}
                    <span data-numeric className="ml-1.5 text-xs text-primary">
                      {num(hit.count)}
                    </span>
                  </span>
                  {hit.snippets.map((s, i) => (
                    <span key={i} className="mt-0.5 block truncate text-xs opacity-60">
                      {s}
                    </span>
                  ))}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
