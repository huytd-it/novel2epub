// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { ProperNamesDialog } from "./ProperNamesDialog";

const mocks = vi.hoisted(() => ({ post: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { post: mocks.post } }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/components/ui/Modal", () => ({
  Modal: ({ open, children, footer }: any) => open ? <div>{children}{footer}</div> : null,
}));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; vi.clearAllMocks(); });

function mount(includeTerms = false) {
  mocks.post.mockResolvedValue({ candidates: [], scanned_chapters: 1, queued: 0 });
  const client = new QueryClient();
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter>
    <ProperNamesDialog open slug="demo" chapterIndexes={[]} onClose={() => {}} includeTerms={includeTerms} />
  </MemoryRouter></QueryClientProvider>);
}

it("defaults glossary to terms and lets the user rescan names only", async () => {
  mount(true);
  await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  expect(mocks.post.mock.calls[0][1].body).toEqual({
    chapter_indexes: null, translate: true, include_terms: true, dry_run: true,
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
