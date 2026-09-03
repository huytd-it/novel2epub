import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconPlus } from "@/components/icons";
import { useUploadChaptersToEbook, type UploadAppendResult } from "@/lib/upload";

/** Nút "Upload thêm chương" — bổ sung chương từ file .txt/.epub vào ebook
    đã có. Chỉ thêm index thiếu, không ghi đè, không mất chương cũ. */
export function UploadChaptersButton({ slug }: { slug: string }) {
  const toast = useToast();
  const mutation = useUploadChaptersToEbook(slug);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<UploadAppendResult | null>(null);

  const close = () => {
    if (!mutation.isPending) {
      setOpen(false);
      setResult(null);
    }
  };

  const submit = async (file: File | null) => {
    if (!file) return;
    if (!/\.(txt|epub)$/i.test(file.name)) {
      toast("Chỉ chấp nhận file .txt và .epub.", "error");
      return;
    }
    try {
      const res = await mutation.mutateAsync(file);
      setResult(res);
      toast(`Đã thêm ${res.added} chương, bỏ qua ${res.skipped} chương đã có (tổng ${res.total}).`);
    } catch (error) {
      toast(error instanceof Error ? error.message : String(error), "error");
    }
  };

  return (
    <>
      <Button icon={<IconPlus size={14} />} onClick={() => { setResult(null); setOpen(true); }}>
        Upload thêm chương
      </Button>
      <Modal
        open={open}
        onClose={close}
        title="Upload thêm chương"
        footer={<Button onClick={close} disabled={mutation.isPending}>Đóng</Button>}
      >
        <div className="grid gap-3">
          <Field label="Chọn file" hint="TXT tách theo tiêu đề chương · EPUB tách theo file con. Index rút từ tiêu đề: đã có raw thì bỏ qua, chưa có thì lấp đúng index đó.">
            <input
              type="file"
              accept=".txt,.epub"
              className="file-input file-input-sm w-full"
              disabled={mutation.isPending}
              onChange={(e) => submit(e.target.files?.[0] ?? null)}
            />
          </Field>
          {mutation.isPending ? <p className="text-sm opacity-60">Đang đọc file…</p> : null}
          {result ? (
            <div className="grid gap-1 text-sm" aria-live="polite">
              <p>
                <Badge tone="celadon">+{result.added} chương</Badge>{" "}
                <Badge tone="gold">bỏ qua {result.skipped}</Badge>{" "}
                <span className="text-xs opacity-60">tổng {result.total} chương</span>
              </p>
              {result.added_indexes.length ? (
                <p className="text-xs opacity-70">Index đã thêm: {result.added_indexes.join(", ")}</p>
              ) : null}
              {result.skipped_titles.length ? (
                <ul className="max-h-40 overflow-auto rounded-box border border-base-300 bg-base-200/30 px-3 py-2 text-xs">
                  {result.skipped_titles.map((title, index) => (
                    <li key={index} className="truncate py-0.5" title={title}>
                      Bỏ qua: {title || <span className="opacity-50">(không tiêu đề)</span>}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
