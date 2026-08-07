import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "N2E_");
  // Tauri loads the bundle off `tauri://` with no server prefix, so it needs
  // relative asset URLs; FastAPI serves the same build under /app/.
  const isTauri = env.N2E_TARGET === "tauri";

  return {
    base: isTauri ? "./" : "/app/",
    // Cho phép code client đọc `N2E_API_BASE` — bản deploy lên Vercel/Cloudflare
    // Pages phải biết backend ở đâu ngay từ lần tải đầu, không thể chờ người
    // dùng nhập vào trang Kết nối.
    envPrefix: ["VITE_", "N2E_"],
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    build: {
      outDir: "../app/webui",
      emptyOutDir: true,
      sourcemap: mode !== "production",
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
        ].map((path) => [
          path,
          { target: "http://127.0.0.1:8011", changeOrigin: true },
        ]),
      ),
    },
  };
});
