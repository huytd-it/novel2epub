// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { GlossaryExtractor, GlossaryExtractPage } from "./GlossaryExtractPage";

const mocks = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { post: mocks.post } }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => mocks.toast }));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; vi.clearAllMocks(); });

function mount(includeTerms = false, withCandidate = false) {
  mocks.post.mockResolvedValue({ candidates: withCandidate ? [{ source: "灵石", kind: "term", frequency: 3,
    confidence: 0.7, chapter_index: 1, context: "灵石。", status: "new" }] : [], scanned_chapters: 1, queued: 1 });
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
    chapter_indexes: null, translate: true, translate_engine: "localmt", include_terms: true, dry_run: true,
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

it("queues selected candidates with explicit Local MT and no modal", async () => {
  mount(true, true);
  await screen.findByText("灵石");
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByTitle("Chọn tất cả tên chờ duyệt"));
  fireEvent.click(screen.getByRole("button", { name: /Dịch thô & đưa/ }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
  expect(mocks.post.mock.calls[1][1].body).toMatchObject({ sources: ["灵石"], translate: true, translate_engine: "localmt" });
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
