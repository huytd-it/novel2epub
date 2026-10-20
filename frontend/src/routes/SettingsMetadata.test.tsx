// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NovelTab } from "./SettingsPage";
import type { EbookSettings } from "@/lib/settings";

const mocks = vi.hoisted(() => ({ post: vi.fn(), save: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { post: mocks.post } }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/settings", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/settings")>(),
  useSaveSettings: () => ({ mutate: mocks.save, isPending: false }),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const server = {
  raw_title: "原书名", raw_author: "原作者",
  title: "Tên cũ", author: "Tác giả", description: "Mô tả cũ", subjects: "Phiêu lưu",
  language: "vi", publisher: "", pubdate: "", series: "", series_index: "",
  identifier: "", cover_url: "",
} as EbookSettings["novel"];

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <NovelTab slug="demo" server={server} />
  </QueryClientProvider>);
}

it("generates all metadata into a draft and only persists on Save", async () => {
  mocks.post.mockResolvedValue({ title: "Tên mới", author: "Tác giả Việt", description: "Giới thiệu mới",
    subjects: ["Kỳ ảo", "Phiêu lưu"], errors: {} });
  mount();
  fireEvent.click(screen.getByRole("button", { name: "AI tạo metadata" }));
  await screen.findByDisplayValue("Tên mới");
  expect(mocks.post.mock.calls[0][1].body).toMatchObject({
    engine: "ai", generate: true, ebook_slug: "demo", subjects: ["Phiêu lưu"],
    title: "原书名", author: "原作者",
  });
  expect((within(screen.getByRole("group", { name: "Chủ đề (Thể loại)" })).getByRole("textbox") as HTMLTextAreaElement).value)
    .toBe("Kỳ ảo\nPhiêu lưu");
  expect(mocks.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Lưu" }));
  expect(mocks.save.mock.calls[0][0]).toMatchObject({ title: "Tên mới", subjects: "Kỳ ảo\nPhiêu lưu" });
  expect(mocks.save.mock.calls[0][0]).toMatchObject({ raw_title: "原书名", raw_author: "原作者" });
});

it("preserves edits made while generation is pending", async () => {
  let resolve!: (value: unknown) => void;
  mocks.post.mockReturnValue(new Promise(done => { resolve = done; }));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "AI tạo metadata" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalled());
  fireEvent.change(within(screen.getByRole("group", { name: "Tiêu đề" })).getByRole("textbox"),
    { target: { value: "Tên tự sửa" } });
  resolve({ title: "Tên AI", author: "Tác giả", description: "Mô tả AI", subjects: [], errors: {} });
  await screen.findByDisplayValue("Mô tả AI");
  expect(screen.getByDisplayValue("Tên tự sửa")).toBeTruthy();
});

it("keeps the original draft on API failure", async () => {
  mocks.post.mockRejectedValue(new Error("LLM không kết nối được"));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "AI tạo metadata" }));
  await waitFor(() => expect(mocks.toast).toHaveBeenCalledWith("LLM không kết nối được", "error"));
  expect(screen.getByDisplayValue("Tên cũ")).toBeTruthy();
  expect(mocks.save).not.toHaveBeenCalled();
});
