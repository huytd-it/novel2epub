/**
 * Đường dẫn nào thuộc về React Router (phải trả `index.html`) chứ không phải
 * endpoint của FastAPI — dùng cho `bypass` của dev proxy trong `vite.config.ts`.
 *
 * Vì sao cần: vài endpoint file nằm NGAY DƯỚI prefix của trang SPA
 * (`/sources/export`, `/storage/{slug}/archive`, `/ebooks/{slug}/toc.csv`), và
 * `<a href>` tải file gửi kèm `Accept: text/html,...` y hệt một lần điều hướng
 * trang. Nếu bypass theo `Accept` thì Vite trả index.html cho các URL đó —
 * trình duyệt tải về file HTML thay vì YAML/CSV/zip. `curl` (Accept mặc định
 * không khai báo `text/html`) thì vẫn chạy được, nên lỗi này rất khó phát hiện
 * bằng tay.
 *
 * Danh sách dưới phải khớp route trang trong `src/main.tsx`. Thêm trang mới thì
 * thêm vào đây, nếu không trang đó sẽ bị proxy tới FastAPI (thường ra 404/405).
 */

/** Trang ở gốc, so khớp CHÍNH XÁC đường dẫn (đã bỏ query string). */
export const SPA_PAGES: ReadonlySet<string> = new Set([
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
]);

/**
 * `/ebooks` là ngoại lệ: dưới prefix này lẫn trang lẫn endpoint file
 * (`toc.csv`, `cover`, `download`, `config/export`) nên phải khớp theo route
 * trang thay vì theo prefix. `toc.csv` cố tình không nằm trong danh sách.
 */
const SPA_EBOOK_PAGE =
  /^\/ebooks\/[^/]+(?:\/(?:chapters|read|build|settings|glossary|ai-harness|characters)(?:\/\d+)?)?\/?$/;

/** `true` nếu `url` là route trang của SPA (query string không quan trọng). */
export function isSpaPage(url: string): boolean {
  const path = url.split("?")[0].split("#")[0];
  return SPA_PAGES.has(path) || SPA_EBOOK_PAGE.test(path);
}
