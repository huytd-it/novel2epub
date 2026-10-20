// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { GlossaryExtractor, GlossaryExtractPage } from "./GlossaryExtractPage";

const mocks = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { post: mocks.post, get: mocks.get } }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => mocks.toast }));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; sessionStorage.clear(); vi.clearAllMocks(); });

function mount(includeTerms = false, withCandidate = false, count = 1) {
  mocks.post.mockResolvedValue({ candidates: withCandidate ? ["灵石", "神功"].slice(0, count).map(source => ({ source, kind: "term", frequency: 3,
    confidence: 0.7, chapter_index: 1, context: `${source}。`, status: "new" })) : [], scanned_chapters: 1, queued: 1 });
  const client = new QueryClient();
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter>
    <GlossaryExtractor slug="demo" chapterIndexes={[]} includeTerms={includeTerms} />
  </MemoryRouter></QueryClientProvider>);
}

it("defaults glossary to terms and lets the user rescan names only", async () => {
  mount(true);
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  expect(mocks.post.mock.calls[0][1].body).toEqual({
    chapter_indexes: null, translate: false, include_terms: true, dry_run: true,
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "Bao gồm thuật ngữ lặp" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[1][1].body.include_terms).toBe(false);
});

it("keeps the name-only action compatible", async () => {
  mount();
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  expect(mocks.post.mock.calls[0][1].body.include_terms).toBe(false);
});

it("queues untranslated candidates as Han without calling an engine", async () => {
  mount(true, true);
  await screen.findByText("灵石");
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Đưa.*vào hàng chờ/ }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[1][1].body).toMatchObject({ sources: ["灵石"], translate: false, targets: {} });
});

it("defaults to Local MT, translates sequential terms and both columns, then queues edited preview", async () => {
  mount(true, true, 2);
  await screen.findByText("灵石");
  expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("localmt");
  mocks.post.mockImplementation((url) => Promise.resolve(url.endsWith("/translate") ? {
    job_id: "preview-local", category: "local-mt",
  } : { candidates: [], queued: 2 }));
  mocks.get.mockResolvedValue({ id: "preview-local", state: "done", log: [], outcome: {
    entries: ["灵石", "神功"].map(source => ({ source, target: `Việt ${source}`,
      context_target: `Ngữ cảnh Việt ${source}`, engine: "localmt", error: "" })),
  } });
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Dịch 2 dòng đã chọn/ }));
  await screen.findByText("Ngữ cảnh Việt 神功");
  const calls = mocks.post.mock.calls.filter(([url]) => url.endsWith("/translate"));
  expect(calls).toHaveLength(1);
  expect(calls[0][1].body).toEqual({ engine: "localmt", entries: [
    { source: "灵石", context: "灵石。" }, { source: "神功", context: "神功。" },
  ] });
  fireEvent.change(screen.getByRole("textbox", { name: "Bản dịch 灵石" }), { target: { value: "linh thạch" } });
  fireEvent.click(screen.getByRole("button", { name: /Đưa.*vào hàng chờ/ }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(3));
  expect(mocks.post.mock.calls[2][1].body.targets).toEqual({ "灵石": "linh thạch", "神功": "Việt 神功" });
  expect(mocks.post.mock.calls[2][1].body.translate).toBe(false);
});

it("sends multiple selected rows in one LLM preview request", async () => {
  mount(true, true, 2);
  await screen.findByText("灵石");
  mocks.post.mockResolvedValue({ job_id: "preview-llm", category: "ai-translate" });
  mocks.get.mockResolvedValue({ id: "preview-llm", state: "done", log: [], outcome: {
    entries: ["灵石", "神功"].map(source => ({ source, target: `Việt ${source}`,
      context_target: `LLM ${source}`, engine: "openai", error: "" })),
  } });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "openai" } });
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Dịch 2 dòng đã chọn/ }));
  await screen.findByText("LLM 神功");
  expect(mocks.post.mock.calls[1][1].body.engine).toBe("openai");
  expect(mocks.post.mock.calls[1][1].body.entries).toHaveLength(2);
  expect(mocks.post).toHaveBeenCalledTimes(2);
});

it("tracks pending jobs and allows cancellation through Job Queue", async () => {
  mount(true, true);
  await screen.findByText("灵石");
  mocks.post.mockResolvedValue({ job_id: "waiting", category: "local-mt" });
  mocks.get.mockResolvedValue({ id: "waiting", state: "pending", log: [] });
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Dịch 1 dòng đã chọn/ }));
  await screen.findByText("Job dịch: Đang chờ");
  expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
  expect(screen.getByRole("link", { name: "Mở Job Queue" }).getAttribute("href")).toBe("/queue");
  mocks.get.mockResolvedValue({ id: "waiting", state: "cancelled", log: [] });
  fireEvent.click(screen.getByRole("button", { name: "Hủy job dịch" }));
  await screen.findByText("Job dịch: Đã hủy");
  expect(mocks.post.mock.calls[2][0]).toBe("/api/queue/waiting/cancel");
});

it("restores the job result after returning to the extraction page", async () => {
  sessionStorage.setItem("glossary-extract-preview:demo::true", JSON.stringify({ id: "saved", terms: true }));
  mocks.get.mockResolvedValue({ id: "saved", state: "done", log: [], outcome: { entries: [{
    source: "灵石", target: "linh thạch", context_target: "ngữ cảnh đã lưu", engine: "localmt", error: "",
  }] } });
  mount(true, true);
  await screen.findByText("ngữ cảnh đã lưu");
  expect(mocks.post).toHaveBeenCalledTimes(1); // scan only, no duplicate translation
  expect(mocks.get.mock.calls[0][0]).toMatch(/translate\/saved$/);
});

it("does not accidentally enqueue a duplicate when status polling fails", async () => {
  mount(true, true);
  await screen.findByText("灵石");
  mocks.post.mockResolvedValue({ job_id: "unknown-state", category: "local-mt" });
  mocks.get.mockRejectedValue(new Error("network unavailable"));
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Dịch 1 dòng đã chọn/ }));
  await screen.findByText("Job dịch: Không lấy được trạng thái");
  expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true);
  expect(mocks.post).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Bỏ theo dõi (không hủy job)" }));
  expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(false);
  expect(mocks.post).toHaveBeenCalledTimes(2);
});

it("loads a standalone route with chapter scope preserved in URL", async () => {
  mocks.post.mockResolvedValue({ candidates: [], scanned_chapters: 2, queued: 0 });
  const client = new QueryClient();
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/ebooks/demo/glossary/extract?terms=false&chapters=101,205"]}>
    <Routes><Route path="/ebooks/:slug/glossary/extract" element={<GlossaryExtractPage />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
  expect(screen.getByRole("heading", { name: "Trích tên riêng" })).toBeTruthy();
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  expect(mocks.post.mock.calls[0][1].body).toMatchObject({ chapter_indexes: [101, 205], include_terms: false });
  expect(screen.getByRole("link", { name: "Về trang Chương" }).getAttribute("href")).toBe("/ebooks/demo");
});
