import { describe, it, expect } from "vitest";
import { isSpaPage } from "./spaRoutes";

describe("isSpaPage (bypass của dev proxy)", () => {
  it("trang gốc là route SPA", () => {
    for (const path of [
      "/",
      "/library",
      "/library/new",
      "/sources",
      "/storage",
      "/automation",
      "/idioms",
      "/wireguard",
      "/queue",
      "/logs",
      "/connection",
      "/dashboard",
      "/tailscale",
      "/local-mt",
      "/translate-settings",
      "/ai-providers",
      "/system",
    ]) {
      expect(isSpaPage(path), path).toBe(true);
    }
  });

  it("route trang của ebook là SPA", () => {
    for (const path of [
      "/ebooks/abc",
      "/ebooks/abc/chapters",
      "/ebooks/abc/chapters/12",
      "/ebooks/abc/read",
      "/ebooks/abc/read/3",
      "/ebooks/abc/build",
      "/ebooks/abc/settings",
      "/ebooks/abc/glossary",
      "/ebooks/abc/ai-harness",
      "/ebooks/abc/characters",
      "/ebooks/abc/",
    ]) {
      expect(isSpaPage(path), path).toBe(true);
    }
  });

  // Regression: `<a href>` tải file gửi `Accept: text/html` y hệt điều hướng
  // trang. Nếu endpoint file bị bypass, Vite trả index.html và trình duyệt tải
  // về file HTML — `/sources/export` hỏng đúng như vậy.
  it("endpoint tải file dưới cùng prefix KHÔNG phải SPA", () => {
    for (const path of [
      "/sources/export",
      "/storage/abc/archive",
      "/ebooks/abc/toc.csv",
      "/ebooks/abc/cover",
      "/ebooks/abc/download",
      "/ebooks/abc/config/export",
      "/download",
      "/api/ui/sources",
    ]) {
      expect(isSpaPage(path), path).toBe(false);
    }
  });

  it("bỏ qua query string và hash", () => {
    expect(isSpaPage("/storage?tab=epub")).toBe(true);
    expect(isSpaPage("/library#top")).toBe(true);
    expect(isSpaPage("/sources/export?all=1")).toBe(false);
  });
});
