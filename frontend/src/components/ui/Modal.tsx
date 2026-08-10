import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import clsx from "clsx";

import { Button } from "./Button";

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // `showModal()` cho sẵn focus trap, khoá cuộn nền và phím Esc — không cần
    // dựng lại bằng tay.
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={ref} className="modal" onClose={onClose}>
      <div className={clsx("modal-box border border-base-300 p-0", wide && "max-w-3xl")}>
        <div className="flex items-center justify-between border-b border-base-300 px-4 py-3">
          <h3 className="font-display text-base font-semibold">{title}</h3>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Đóng">
            ✕
          </Button>
        </div>
        <div className="scroll-slim max-h-[65vh] overflow-y-auto px-4 py-3">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 border-t border-base-300 px-4 py-3">{footer}</div>
        ) : null}
      </div>
      <form method="dialog" className="modal-backdrop">
        <button type="submit">Đóng</button>
      </form>
    </dialog>
  );
}

export function ConfirmDialog({
  open,
  onCancel,
  onConfirm,
  title,
  body,
  confirmLabel = "Xác nhận",
  confirmDisabled,
  destructive,
  pending,
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  confirmDisabled?: boolean;
  destructive?: boolean;
  pending?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button onClick={onCancel}>Hủy</Button>
          <Button
            variant={destructive ? "danger" : "primary"}
            loading={pending}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-[13px]">{body}</div>
    </Modal>
  );
}
