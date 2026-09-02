import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "N2E_");
  // Tauri loads the bundle off `tauri://` with no server prefix, so it needs
  // relative asset URLs; FastAPI serves the same build at / (root).
  const isTauri = env.N2E_TARGET === "tauri";
  // Backend mà dev server proxy tới. Có máy không bind được 8011 (Windows giữ
  // sẵn dải 8001–8100 cho Hyper-V/WSL) nên cho phép trỏ sang cổng khác qua
  // `N2E_DEV_API_TARGET` trong `frontend/.env.local`.
  const devApiTarget = env.N2E_DEV_API_TARGET || "http://127.0.0.1:8011";

  return {
    base: isTauri ? "./" : "/",
    // Cho phép code client đọc `N2E_API_BASE` — bản deploy lên Vercel/Cloudflare
    // Pages phải biết backend ở đâu ngay từ lần tải đầu, không thể chờ người
    // dùng nhập vào trang Kết nối.
    envPrefix: ["VITE_", "N2E_"],
    plugins: [
      react(),
      tailwindcss(),
      // Service worker không chạy được trên `tauri://` nên bỏ hẳn khỏi bản
      // desktop. Bản web lấy scope `/` (FastAPI phục vụ SPA ở gốc).
      isTauri
        ? null
        : VitePWA({
            registerType: "autoUpdate",
            includeAssets: ["favicon.ico", "icons/favicon-16.png", "icons/favicon-32.png", "icons/icon-192.png", "icons/icon-512.png", "icons/maskable-512.png"],
            manifest: {
              name: "novel2epub",
              short_name: "novel2epub",
              description: "Xưởng crawl, dịch và đóng gói EPUB",
              lang: "vi",
              start_url: "/",
              scope: "/",
              display: "standalone",
              orientation: "portrait",
              background_color: "#0e1116",
              theme_color: "#0e1116",
              icons: [
                { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
                { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
                {
                  src: "icons/maskable-512.png",
                  sizes: "512x512",
                  type: "image/png",
                  purpose: "maskable",
                },
              ],
            },
            workbox: {
              // Asset đã hash nên cache vĩnh viễn là an toàn; font + ảnh nằm
              // trong danh sách precache. Không cache API — dữ liệu luôn mới.
              globPatterns: ["**/*.{js,css,html,svg,png,woff2,woff,eot,ttf,ico}"],
              navigateFallback: "/index.html",
              navigateFallbackDenylist: [/^\/api\//, /^\/opds\//],
            },
            devOptions: { enabled: false },
          }),
    ],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    build: {
      outDir: "../app/webui",
      emptyOutDir: true,
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router"],
            query: ["@tanstack/react-query"],
            icons: ["react-icons"],
            vendor: ["clsx", "qrcode.react"],
          },
        },
      },
    },
    server: {
      port: 5183,
      proxy: Object.fromEntries(
        [
          "/api",
          "/opds",
          "/ebooks",
          "/library",
          "/sources",
          "/storage",
          "/wireguard",
          "/automation",
          "/settings",
          "/jobs",
          "/chapters",
          "/idioms",
          "/download",
          "/static",
        ].map((path) => {
          const isApi = path === "/api" || path === "/opds";
          return [
            path,
            {
              target: devApiTarget,
              changeOrigin: true,
              // SPA route trùng prefix legacy (vd GET /sources) — trình duyệt
              // gửi Accept: text/html khi Ctrl+F5 / gõ trực tiếp. Bỏ qua proxy
              // để Vite trả index.html cho React Router thay vì proxy tới
              // FastAPI và nhận 405 Method Not Allowed (chỉ có POST /sources).
              // /api và /opds là JSON thuần nên luôn proxy.
              bypass: isApi
                ? undefined
                : ((req: any) => {
                    const accept = (req.headers.accept as string) || "";
                    if (req.method === "GET" && accept.includes("text/html")) return req.url;
                  }) as any,
            },
          ];
        }),
      ),
    },
  };
});
