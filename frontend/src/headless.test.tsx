import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router";
import React from "react";

const captured: Record<string, unknown>[] = [];

vi.mock("@/lib/settings", async () => {
  const actual = await vi.importActual<typeof import("@/lib/settings")>("@/lib/settings");
  return {
    ...actual,
    useEbookSettings: () => ({
      data: {
        slug: "s" + Math.random(),
        novel: {},
        source: {
          toc_url: "https://www.sudugu.org/32/",
          chapter_link_pattern: "/\\d+/\\d+\\.html",
          max_chapters: 0,
          delay_seconds: 1,
          max_workers: 1,
          concurrency_cap: 0,
          content_selector: ".con",
          scrapling_mode: "stealthy",
          solve_cloudflare: true,
          network_idle: true,
          impersonate: "",
          proxy: "",
          dns_over_https: false,
          next_page_selector: ".prenext span:last-child a",
          next_page_url_pattern: "",
          max_pages_per_chapter: 10,
          toc_next_page_selector: ".gr",
          toc_max_pages: 5,
          retry_attempts: 3,
          retry_delay_seconds: 5,
          retry_backoff: 2,
          retry_max_delay_seconds: 120,
          retry_respect_retry_after: true,
          headless: true,
          strip_patterns: "",
        },
        translate: {},
        ai: {},
        global_ai: { base_url: "", api_key: "", api_key_configured: false, translation_model: "", assistant_model: "", timeout_seconds: 15, temperature: 0.7 },
        opds: { token: "", token_configured: false, cors_origins: "", auto_build: false },
        reader: {},
        output: {},
        meta: { source_name: "sudugu", source_detected: false, source_presets: [], overridden_fields: [], genres: [] },
      },
      isPending: false,
      error: null,
    }),
    useSaveSettings: () => ({
      mutate: (payload: unknown) => { captured.push(payload as any); },
      isPending: false,
      mutateAsync: async () => {},
    }),
  };
});

import { SettingsPage } from "@/routes/SettingsPage";

describe("headless checkbox", () => {
  it("updates draft when toggled and sends false", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/e/s"]}>
          <Routes>
            <Route path="/e/:slug" element={children} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
    const view = render(<SettingsPage />, { wrapper });
    // Click the "Nguồn" tab
    await user.click(screen.getByRole("tab", { name: /Nguồn/i }));
    const box = screen.getByLabelText(/Chạy headless/i) as HTMLInputElement;
    expect(box.checked).toBe(true);
    await user.click(box);
    expect(box.checked).toBe(false);
    // Simulate a background react-query refetch: rerender with a NEW server
    // reference (mock returns a fresh object each call). Before the fix this
    // clobbered the user's toggle via useEffect(() => setDraft(server), ...).
    view.rerender(<SettingsPage />);
    expect((screen.getByLabelText(/Chạy headless/i) as HTMLInputElement).checked).toBe(false);
    const saveBtn = screen.getByRole("button", { name: /Lưu/i });
    await user.click(saveBtn);
    expect(captured.length).toBeGreaterThan(0);
    expect((captured[0] as any).headless).toBe(false);
  });
});
