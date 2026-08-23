import { useEffect, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import {
  confirmBulk,
  previewBulk,
  type BulkAction,
  type BulkConfirmResult,
  type BulkPreview,
} from "@/lib/bulk";
import { num } from "@/lib/format";
import { Button } from "@/components/ui/Button";
import { Loading } from "@/components/ui/Loading";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";

/**
 * Hộp thoại preview → confirm cho một hành động hàng loạt.
 *
 * Mở ra là gọi `/bulk-preview` ngay (không đổi trạng thái, không gọi model),
 * hiển thị số chương đủ điều kiện / bị chặn kèm lý do rồi mới bật nút xác
 * nhận. Confirm nhận token từ preview; token hết hạn / config hoặc workspace
 * chương đổi giữa chừng → 409, hộp thoại tự preview lại cho mới.
 */
export function BulkPreviewDialog({
  open,
  onClose,
  slug,
  action,
  indexes,
  branch = "",
  force = false,
  title,
  body,
  bodyExtra,
  confirmLabel = "Xác nhận",
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  action: BulkAction;
  indexes: number[];
  branch?: string;
  force?: boolean;
  title: string;
  body?: ReactNode;
  /** Điều kiện bổ sung hiển thị ngay dưới đoạn body (vd checkbox force) —
      đổi giá trị bên trong sẽ làm hộp thoại preview lại tự động. */
  bodyExtra?: ReactNode;
  confirmLabel?: string;
  onDone: (result: BulkConfirmResult) => void;
}) {
  const toast = useToast();
  const indexesKey = indexes.join(",");

  const preview = useMutation({
    mutationFn: () => previewBulk(slug, { action, indexes, branch, force }),
  });
  const confirm = useMutation({
    mutationFn: (token: string) => confirmBulk(slug, token),
  });

  // Preview lại mỗi lần mở hoặc bộ tham số đổi.
  useEffect(() => {
    if (!open) return;
    preview.reset();
    confirm.reset();
    preview.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, slug, action, indexesKey, branch, force]);

  const data: BulkPreview | undefined = preview.data;
  const loading = preview.isPending || (open && !data);
  const error = preview.error
    ? preview.error instanceof Error
      ? preview.error.message
      : String(preview.error)
    : null;
  const confirmError = confirm.error
    ? confirm.error instanceof Error
      ? confirm.error.message
      : String(confirm.error)
    : null;

  const eligibleCount = data?.eligible ?? 0;
  const blockedItems = data?.chapters.filter((c) => !c.ok) ?? [];

  const handleConfirm = () => {
    if (!data) return;
    confirm.mutate(data.token, {
      onSuccess: (result) => {
        toast(
          result.status === "queued"
            ? `Đã xếp ${result.total ?? eligibleCount} chương vào hàng đợi.`
            : `Xong ${result.total ?? eligibleCount} chương.`,
        );
        onDone(result);
        onClose();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          // Config / workspace chương đã đổi kể từ lúc preview → preview lại.
          toast("Dữ liệu hoặc cấu hình đã đổi — đang preview lại…", "error");
          preview.reset();
          confirm.reset();
          preview.mutate();
        }
      },
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      wide
      footer={
        <>
          <Button onClick={onClose} disabled={confirm.isPending}>
            Hủy
          </Button>
          <Button
            variant="primary"
            loading={confirm.isPending}
            disabled={loading || eligibleCount === 0}
            onClick={handleConfirm}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {body ? <p className="mb-3 text-[13px] opacity-70">{body}</p> : null}
      {bodyExtra ? <div className="mb-3">{bodyExtra}</div> : null}

      {loading ? (
        <Loading label="Đang đánh giá các chương đã chọn" />
      ) : error ? (
        <div className="rounded-box border border-error/30 bg-error/5 px-3 py-2 text-[13px] text-error">
          {error}
        </div>
      ) : data ? (
        <div className="space-y-3">
          {confirmError ? (
            <div className="rounded-box border border-error/30 bg-error/5 px-3 py-2 text-[13px] text-error">
              {confirmError}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
            <span>
              <span data-numeric>{num(data.total)}</span> chương khớp
            </span>
            <span className="text-success">
              <span data-numeric>{num(data.eligible)}</span> đủ điều kiện
            </span>
            {data.blocked > 0 ? (
              <span className="text-warning">
                <span data-numeric>{num(data.blocked)}</span> bị chặn
              </span>
            ) : null}
          </div>

          {data.estimates.input_tokens > 0 ? (
            <div className="rounded-box border border-base-300 bg-base-200/40 px-3 py-2 text-[12px] opacity-80">
              Ước lượng gọi model: <span data-numeric>{num(data.estimates.input_tokens)}</span>{" "}
              token đầu vào · <span data-numeric>{num(data.estimates.output_tokens)}</span> token
              đầu ra
              {data.estimates.cost_usd > 0 ? (
                <> · ${data.estimates.cost_usd.toFixed(2)}</>
              ) : null}
            </div>
          ) : null}

          {blockedItems.length > 0 ? (
            <div>
              <p className="mb-1 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40">
                Chương bị chặn
              </p>
              <ul className="scroll-slim max-h-56 space-y-1 overflow-y-auto rounded-box border border-base-300 bg-base-100 px-3 py-2 text-[12px]">
                {blockedItems.map((c) => (
                  <li key={c.index} className="flex items-center gap-2">
                    <span data-numeric className="shrink-0 opacity-40">
                      {c.index}
                    </span>
                    <span className="min-w-0 truncate">{c.title}</span>
                    <span className="ml-auto shrink-0 pl-2 text-warning">{c.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {eligibleCount === 0 ? (
            <p className="text-[13px] text-warning">
              Không có chương nào đủ điều kiện — không thể xác nhận.
            </p>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
