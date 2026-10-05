// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import type { ComponentProps } from "react";
import type { ProofreadingPanel } from "@/components/chapter/ProofreadingPanel";

const mocks = vi.hoisted(() => ({ selectBook: vi.fn(), toast: vi.fn(), post: vi.fn(), get: vi.fn() }));
let panel: ComponentProps<typeof ProofreadingPanel>;
vi.mock("@/app/Shell", () => ({ Page: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("@/lib/books", () => ({ useCurrentBook: () => ["demo", mocks.selectBook] }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/components/ChapterStrip", () => ({ ChapterStrip: () => null, ChapterLegend: () => null }));
vi.mock("@/components/chapter/ProofreadingScan", () => ({
  ProofreadingScan: ({ onCodesChange, onReport }: { onCodesChange: (codes: string[]) => void; onReport: (report: any) => void }) => {
    React.useEffect(() => { onReport({ scan: true, checked: 3, chapters: [{ index: 101, title: "Chương 101", issues: [{ code: "han_remaining", level: "warning", message: "Chữ Hán" }] }] }); }, [onReport]);
    return <section aria-label="Soát lỗi hàng loạt">
    <button onClick={() => onCodesChange(["han_remaining"])}>Chọn mã mock</button>
    <button onClick={() => onCodesChange([])}>Xóa mã mock</button>
  </section>;
  },
}));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post }, apiUrl: (path: string) => path }));
vi.mock("@/components/ui/Modal", () => ({
  Modal: () => null,
  ConfirmDialog: () => null,
}));
vi.mock("@/components/chapter/ProofreadingPanel", async () => {
  const actual = await vi.importActual<typeof import("@/components/chapter/ProofreadingPanel")>("@/components/chapter/ProofreadingPanel");
  return { ...actual, ProofreadingPanel: (props: ComponentProps<typeof ProofreadingPanel>) => {
    panel = props;
    return props.open ? <div role="dialog" aria-label="Soát lỗi">
      <button onClick={() => props.onCommitted()}>Hoàn tất job mock</button>
      <button onClick={props.onClose}>Đóng soát lỗi</button>
    </div> : null;
  } };
});
vi.mock("@/lib/ebook", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ebook")>("@/lib/ebook");
  return { ...actual,
    useEbook: () => ({ isPending: false, error: null, data: {
      title: "Truyện kiểm thử", total: 3, raw_count: 3, translated_count: 3,
      counts: {}, strip: "", active_jobs: [], has_manifest: true, epub_exists: false,
      epub_size: 0, reader_configured: false,
    } }),
    useChapters: () => ({ isPending: false, isFetching: false, data: {
      total: 3, matched: 3, indexes: [101, 103, 205],
      rows: [101, 103].map(index => ({
        index, visible_title: `Chương ${index}: Thử`, title_zh: "", title_format_ok: true,
        has_raw: true, has_translation: true, has_local_mt_translation: true,
        has_ai_translation: false, active_branch: "local_mt", skipped: false,
        missing_fields: [],
        zh_char_count: 10, word_count: 10,
      })),
    } }),
  };
});

import { EbookPage } from "./EbookPage";

function ChangeBook() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/ebooks/other")}>Đổi truyện mock</button>;
}
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/ebooks/demo"]}>
    <ChangeBook /><Routes><Route path="/ebooks/:slug" element={<EbookPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
  return client;
}
afterEach(() => {
  cleanup();
  clients.splice(0).forEach(client => client.clear());
  localStorage.clear();
  vi.clearAllMocks();
});

describe("EbookPage proofreading integration", () => {
  it("shows an icon-only error link inside the TOC row, not a separate error table", () => {
    mount();
    const link = screen.getByRole("link", { name: "Sửa lỗi chương 101" });
    expect(link.getAttribute("href")).toBe("/ebooks/demo/chapters/101?edit=1");
    expect(link.textContent).toBe("");
    expect(link.querySelector("svg")).toBeTruthy();
    expect(link.closest("tr")?.textContent).toContain("Chương 101");
    expect(screen.queryByRole("link", { name: "Sửa lỗi chương 103" })).toBeNull();
    expect(screen.queryByRole("table", { name: "Chapter có lỗi" })).toBeNull();
  });
  it("keeps proofreading closed until selecting a fix scope", () => {
    mount();
    expect(panel.open).toBe(false);
    expect(panel.indexes).toEqual([]);
    expect(panel.codes).toEqual([]);
    expect(panel.getDraft().editing).toBe(false);
    expect(panel.applyDraft(panel.getDraft(), "unexpected draft")).toBe(false);
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it("uses all matched indexes including off-page rows and keeps selection after completion", () => {
    const client = mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: /Chọn tất cả 3 chương khớp/ }));
    const section = screen.getByRole("region", { name: "Soát lỗi hàng loạt" });
    fireEvent.click(within(section).getByRole("button", { name: "Chọn mã mock" }));
    fireEvent.click(screen.getByRole("button", { name: "Soát lỗi", exact: true }));
    expect(panel.indexes).toEqual([101, 103, 205]);
    expect(panel.codes).toEqual(["han_remaining"]);
    fireEvent.click(screen.getByRole("button", { name: "Hoàn tất job mock" }));
    expect((screen.getByLabelText("Chọn chương 101") as HTMLInputElement).checked).toBe(true);
    expect(panel.open).toBe(true);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["chapters", "demo"] });
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it("batch button uses only selected indexes and preserves captured scope when closed", () => {
    mount();
    fireEvent.click(screen.getByLabelText("Chọn chương 103"));
    fireEvent.click(screen.getByRole("button", { name: "Soát lỗi", exact: true }));
    expect(panel.indexes).toEqual([103]);
    fireEvent.click(screen.getByRole("button", { name: "Đóng soát lỗi" }));
    fireEvent.click(screen.getByRole("button", { name: "Bỏ chọn", exact: true }));
    expect(panel.indexes).toEqual([103]);
    expect(panel.open).toBe(false);
  });
  it("changing books clears selection, code choices and old proofreading context", () => {
    mount();
    fireEvent.click(screen.getByLabelText("Chọn chương 101"));
    fireEvent.click(screen.getByRole("button", { name: "Soát lỗi", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Đổi truyện mock" }));
    expect(panel.slug).toBe("other");
    expect(panel.indexes).toEqual([]);
    expect(panel.codes).toEqual([]);
    expect(panel.open).toBe(false);
    expect(panel.getDraft().slug).toBe("other");
    expect((screen.getByLabelText("Chọn chương 101") as HTMLInputElement).checked).toBe(false);
  });
  it("persists the code filter in localStorage", () => {
    mount();
    const section = screen.getByRole("region", { name: "Soát lỗi hàng loạt" });
    fireEvent.click(within(section).getByRole("button", { name: "Chọn mã mock" }));
    expect(localStorage.getItem("ebooks.demo.proofreadingCode")).toBe("han_remaining");
    fireEvent.click(within(section).getByRole("button", { name: "Xóa mã mock" }));
    expect(localStorage.getItem("ebooks.demo.proofreadingCode")).toBeNull();
  });
});
