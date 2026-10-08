// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mocks = vi.hoisted(() => ({ scan: vi.fn(), scanResult: vi.fn(), state: vi.fn(), queue: vi.fn(), analyze: vi.fn(), save: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.queue, post: mocks.save } }));
vi.mock("@/lib/chapter", async () => {
  const actual = await vi.importActual<typeof import("@/lib/chapter")>("@/lib/chapter");
  return { ...actual, proofreadingApi: { ...actual.proofreadingApi, scan: mocks.scan, scanResult: mocks.scanResult, state: mocks.state, analyze: mocks.analyze } };
});
vi.mock("@/components/ui/Modal", () => ({
  Modal: ({ open, title, children, footer }: { open: boolean; title: string; children: React.ReactNode; footer: React.ReactNode }) => open ? <section role="dialog" aria-label={title}>{children}{footer}</section> : null,
  ConfirmDialog: () => null,
}));
import { ProofreadingScan } from "./ProofreadingScan";
import { ProofreadingChapterPreview } from "./ProofreadingChapterPreview";

const issue = (code: string) => ({ code, level: "warning", message: `Lỗi ${code}`, snippet: "", paraIndex: 0, start: 0, end: 1 });
const report = { scan: true, checked: 4, chapters: [
  { index: 101, title: "Chương 101", issues: [issue("han_remaining")] },
  { index: 205, title: "Chương 205", issues: [issue("double_space")] },
  { index: 306, title: "Chương 306", issues: [], error: "Chưa có nguồn hoàn chỉnh" },
  { index: 407, title: "Chương 407", issues: [] },
] };
const clients: QueryClient[] = [];
function mount(persisted?: typeof report, integrated = false) {
  mocks.scan.mockResolvedValue({ job_id: "scan-1" });
  mocks.queue.mockResolvedValue({ running: [], pending: {}, history: [{ id: "scan-1", state: "done", outcome: { proofreading_report_id: "report-1" } }] });
  mocks.scanResult.mockResolvedValue(report);
  mocks.state.mockImplementation(() => persisted ? Promise.resolve(persisted) : mocks.scan.mock.calls.length ? mocks.scanResult() : Promise.resolve({ scan: true, checked: 0, chapters: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  function Wrapper() {
    const [codes, setCodes] = useState<string[]>([]);
    return <ProofreadingScan slug="demo" codes={codes} onCodesChange={setCodes}
      {...(integrated ? { onReport: () => {} } : {})} />;
  }
  render(<QueryClientProvider client={client}><MemoryRouter><Wrapper /></MemoryRouter></QueryClientProvider>);
}
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks(); });

function mountPreview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter><ProofreadingChapterPreview slug="demo" index={101} onClose={() => {}} onSaved={() => {}} /></MemoryRouter></QueryClientProvider>);
}

describe("scan everything once then filter locally", () => {
  it("integrated mode shows only the filter with no second table and no bulk fix UI", async () => {
    mount(report, true);
    await screen.findByLabelText("Lọc theo mã lỗi đã rà soát");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByLabelText("Lọc theo mã lỗi đã rà soát")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Fix hàng loạt/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /chương chọn để sửa/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Chọn tất cả chương có lỗi/ })).toBeNull();
  });
  it("one click scans without codes/index filters; later selection only changes displayed warnings", async () => {
    mount();
    expect(mocks.scan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Rà soát tất cả lỗi" }));
    await screen.findByLabelText("Lọc theo mã lỗi đã rà soát");
    expect(mocks.scan).toHaveBeenCalledTimes(1);
    expect(mocks.scan).toHaveBeenCalledWith("demo");
    expect(mocks.state).toHaveBeenCalledWith("demo");
    expect(screen.getByText("Lỗi han_remaining", { exact: false })).toBeTruthy();
    expect(screen.getByText("Lỗi double_space", { exact: false })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Chương 407/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Lọc theo mã lỗi đã rà soát"), { target: { value: "han_remaining" } });
    expect(screen.queryByText("Lỗi double_space", { exact: false })).toBeNull();
    expect(screen.getByText("Lỗi han_remaining", { exact: false })).toBeTruthy();
    expect(mocks.scan).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("Lọc theo mã lỗi đã rà soát"), { target: { value: "" } });
    expect(screen.getByText("Lỗi double_space", { exact: false })).toBeTruthy();
  });
  it("failed report download shows error without enqueueing another scan", async () => {
    mount();
    mocks.scanResult.mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: "Rà soát tất cả lỗi" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Tải lỗi từ DB" })).toBeNull();
    expect(mocks.scan).toHaveBeenCalledTimes(1);
  });
  it("warning table paginates beyond the first report page", async () => {
    mount();
    const rows = Array.from({ length: 31 }, (_, i) => ({ index: 100 + i, title: `Chương ${100 + i}`, issues: [issue("han_remaining")] }));
    mocks.scanResult.mockResolvedValue({ scan: true, checked: 31, chapters: rows });
    fireEvent.click(screen.getByRole("button", { name: "Rà soát tất cả lỗi" }));
    await screen.findByLabelText("Lọc theo mã lỗi đã rà soát");
    expect(screen.queryByRole("link", { name: /Chương 130/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Lọc theo mã lỗi đã rà soát"), { target: { value: "han_remaining" } });
    fireEvent.click(screen.getByRole("button", { name: "Lỗi trang sau" }));
    expect(screen.getByRole("link", { name: /Chương 130/ })).toBeTruthy();
    expect(mocks.scan).toHaveBeenCalledTimes(1);
  });
  it("dropdown contains only scanned codes and switches one display filter", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Rà soát tất cả lỗi" }));
    await screen.findByLabelText("Lọc theo mã lỗi đã rà soát");
    const filter = screen.getByLabelText("Lọc theo mã lỗi đã rà soát") as HTMLSelectElement;
    expect(Array.from(filter.options).map(option => option.value)).toEqual(["", "double_space", "han_remaining"]);
    fireEvent.change(filter, { target: { value: "han_remaining" } });
    expect(screen.queryByText("Lỗi double_space", { exact: false })).toBeNull();
    fireEvent.change(filter, { target: { value: "double_space" } });
    expect(screen.queryByText("Lỗi han_remaining", { exact: false })).toBeNull();
    expect(mocks.scan).toHaveBeenCalledTimes(1);
  });
  it("previews full publication with warnings and manually saves only on explicit Save", async () => {
    const full = "😀 中\n\n" + "Nội dung nguyên vẹn.\n".repeat(150) + "CUỐI CHƯƠNG";
    const base = { index: 101, branch: "local_mt", revision: 4, hash: "source-hash", title: "Chương 101", display_title: "Chương 101", text: full, issues: [issue("han_remaining")] };
    mocks.analyze.mockResolvedValue({ chapters: [base], token: "not-used-to-write" });
    mocks.save.mockResolvedValue({ saved: true, revision: 5, content_hash: "saved-hash" });
    mountPreview();
    await screen.findByText(/CUỐI CHƯƠNG/);
    expect(mocks.analyze).toHaveBeenCalledWith("demo", [101], [], {});
    expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sửa thủ công", exact: true }));
    fireEvent.change(screen.getByLabelText("Nội dung sửa thủ công"), { target: { value: full.replace("中", "Trung") } });
    expect(mocks.save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Lưu sửa thủ công" }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(1));
    expect(mocks.save).toHaveBeenCalledWith("/api/ui/ebooks/demo/chapters/101/translated", { body: expect.objectContaining({
      translated: full.replace("中", "Trung"), branch: "local_mt", expected_rev: 4, expected_hash: "source-hash", expected_publication_branch: "local_mt", expected_publication_title: "Chương 101", proofreading_codes: ["han_remaining"],
    }) });
    await screen.findByText(/ĐÃ LƯU THỦ CÔNG chương 101/);
  });
  it("manual save conflicts keep the user's draft and do not silently retry", async () => {
    mocks.analyze.mockResolvedValue({ chapters: [{ index: 101, branch: "local_mt", revision: 4, hash: "hash", title: "Chương 101", text: "中", issues: [issue("han_remaining")] }] });
    mocks.save.mockRejectedValue(new Error("revision đã đổi"));
    mountPreview();
    await screen.findByRole("button", { name: "Sửa thủ công", exact: true });
    fireEvent.click(screen.getByRole("button", { name: "Sửa thủ công", exact: true }));
    fireEvent.change(screen.getByLabelText("Nội dung sửa thủ công"), { target: { value: "Bản sửa giữ nguyên" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu sửa thủ công" }));
    await screen.findByText(/Chưa lưu: revision đã đổi/);
    expect((screen.getByLabelText("Nội dung sửa thủ công") as HTMLTextAreaElement).value).toBe("Bản sửa giữ nguyên");
    expect(mocks.save).toHaveBeenCalledTimes(1);
  });
  it("loads persisted errors and links to the Chapter editor instead of opening a modal", async () => {
    mount(report);
    await screen.findByLabelText("Lọc theo mã lỗi đã rà soát");
    expect(mocks.scan).not.toHaveBeenCalled();
    const link = screen.getByRole("link", { name: "Mở Chapter để sửa chương 101" });
    expect(link.getAttribute("href")).toBe("/ebooks/demo/chapters/101?edit=1");
    fireEvent.click(link);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocks.analyze).not.toHaveBeenCalled();
    expect(mocks.save).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Tải lỗi từ DB" })).toBeNull();
    expect(mocks.scan).not.toHaveBeenCalled();
  });
});
