// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PronounsDialog } from "./PronounsDialog";
import type { PronounPreview } from "@/lib/pronouns";

const mocks = vi.hoisted(() => ({ preview: vi.fn(), apply: vi.fn() }));
vi.mock("@/lib/pronouns", () => ({ pronounsApi: mocks }));
vi.mock("@/components/ui/Modal", () => ({
  Modal: ({ title, children, footer, onClose, dismissible }: { title: string; children: React.ReactNode; footer: React.ReactNode; onClose: () => void; dismissible: boolean }) =>
    <div role="dialog" aria-label={title}><button disabled={!dismissible} onClick={onClose}>Fermer mock</button>{children}{footer}</div>,
}));

const report: PronounPreview = {
  branch: "ai", indexes: [1, 2], token: "a".repeat(64), scanned: 2, unchanged: 1,
  replacements: 2, skipped: [], chapters: [{ index: 1, title: "Chương 1: Thử", revision: 3,
    replacements: 2, diff: '--- Trước\n+++ Sau\n@@ -1 +1 @@\n-😀 “Tôi chờ mày.”\n+😀 “Ta chờ ngươi.”\n' }],
};

function mount(props: Partial<React.ComponentProps<typeof PronounsDialog>> = {}) {
  const onCommitted = vi.fn();
  const onClose = vi.fn();
  render(<PronounsDialog slug="demo" selectedIndexes={[]} availableIndexes={[1, 2]} onClose={onClose} onCommitted={onCommitted} {...props} />);
  return { onCommitted, onClose };
}
async function preview() {
  fireEvent.change(screen.getByLabelText("Nhánh bản dịch"), { target: { value: "ai" } });
  fireEvent.click(screen.getByRole("button", { name: "Xem trước thay đổi" }));
  await screen.findByLabelText("Bản xem trước xưng hô");
}
afterEach(() => { cleanup(); vi.resetAllMocks(); });
beforeEach(() => { mocks.preview.mockResolvedValue(report); mocks.apply.mockResolvedValue({ applied: [1], failed: [], replacements: 2 }); });

describe("pronoun review dialog", () => {
  it("does not fetch on open and requires an explicit branch", async () => {
    mount();
    expect(mocks.preview).not.toHaveBeenCalled();
    expect(mocks.apply).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Xem trước thay đổi" }) as HTMLButtonElement).disabled).toBe(true);
    await preview();
    expect(mocks.preview).toHaveBeenCalledWith("demo", { branch: "ai", indexes: [1, 2] });
    expect(screen.getByText(/Không gọi AI, không tốn token/)).toBeTruthy();
  });

  it("shows complete before/after and requires review before applying exact preview", async () => {
    const { onCommitted } = mount();
    await preview();
    expect(screen.getByText('-😀 “Tôi chờ mày.”')).toBeTruthy();
    expect(screen.getByText('+😀 “Ta chờ ngươi.”')).toBeTruthy();
    const apply = screen.getByRole("button", { name: "Áp dụng 1 chương đã duyệt" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /Tôi đã xem/ }));
    expect(apply.disabled).toBe(false);
    fireEvent.click(apply);
    await screen.findByLabelText("Kết quả chuẩn hóa");
    expect(mocks.apply).toHaveBeenCalledWith("demo", report);
    expect(onCommitted).toHaveBeenCalledOnce();
    expect(screen.queryByRole("checkbox", { name: /Tôi đã xem/ })).toBeNull();
    expect(screen.getByText(/Đã lưu 1 chương/)).toBeTruthy();
  });

  it("invalidates approval and preview when branch or range changes", async () => {
    mount(); await preview();
    fireEvent.click(screen.getByRole("checkbox", { name: /Tôi đã xem/ }));
    fireEvent.change(screen.getByLabelText("Đến index"), { target: { value: "1" } });
    expect(screen.queryByLabelText("Bản xem trước xưng hô")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Xem trước thay đổi" }));
    await screen.findByLabelText("Bản xem trước xưng hô");
    expect((screen.getByRole("checkbox", { name: /Tôi đã xem/ }) as HTMLInputElement).checked).toBe(false);
    expect(mocks.preview).toHaveBeenLastCalledWith("demo", { branch: "ai", indexes: [1] });
    fireEvent.change(screen.getByLabelText("Nhánh bản dịch"), { target: { value: "local_mt" } });
    expect(screen.queryByLabelText("Bản xem trước xưng hô")).toBeNull();
  });

  it("uses selected chapters including off-page indexes, without silently clipping", async () => {
    mount({ selectedIndexes: [1, 205], availableIndexes: [1, 2, 205] });
    await preview();
    expect(mocks.preview).toHaveBeenCalledWith("demo", { branch: "ai", indexes: [1, 205] });
  });

  it("rejects more than 50 selected chapters", () => {
    mount({ selectedIndexes: Array.from({ length: 51 }, (_, i) => i + 1) });
    fireEvent.change(screen.getByLabelText("Nhánh bản dịch"), { target: { value: "ai" } });
    expect(screen.getByText(/Mỗi lượt tối đa 50 chương/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Xem trước thay đổi" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("handles empty and skipped results without offering a write", async () => {
    mocks.preview.mockResolvedValue({ ...report, chapters: [], replacements: 0, scanned: 1, unchanged: 1, skipped: [{ index: 2, reason: "Chưa dịch" }] });
    mount(); await preview();
    expect(screen.getByText(/Không tìm thấy chỗ cần chuẩn hóa/)).toBeTruthy();
    expect(screen.getByText("Index 2: Chưa dịch")).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(mocks.apply).not.toHaveBeenCalled();
  });

  it("disables dismissal and controls while applying and reports partial failure", async () => {
    let finish!: (value: unknown) => void;
    mocks.apply.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    mount(); await preview();
    fireEvent.click(screen.getByRole("checkbox", { name: /Tôi đã xem/ }));
    fireEvent.click(screen.getByRole("button", { name: "Áp dụng 1 chương đã duyệt" }));
    expect((screen.getByRole("button", { name: "Fermer mock" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("Nhánh bản dịch") as HTMLSelectElement).closest("fieldset")?.disabled).toBe(true);
    finish({ applied: [], replacements: 0, failed: [{ index: 1, code: "document_conflict", error: "Chương đã đổi" }] });
    await screen.findByText("Index 1: Chương đã đổi");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("discards stale preview on apply error and requires a new preview", async () => {
    mocks.apply.mockRejectedValue(new Error("Bản xem trước đã cũ"));
    const { onCommitted } = mount(); await preview();
    fireEvent.click(screen.getByRole("checkbox", { name: /Tôi đã xem/ }));
    fireEvent.click(screen.getByRole("button", { name: "Áp dụng 1 chương đã duyệt" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("Hãy xem trước lại");
    expect(screen.queryByRole("checkbox")).toBeNull();
    await waitFor(() => expect(onCommitted).toHaveBeenCalledOnce());
    expect(mocks.apply).toHaveBeenCalledOnce();
  });
});
