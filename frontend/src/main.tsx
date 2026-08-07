import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import "@fontsource-variable/bricolage-grotesque";
import "@fontsource/be-vietnam-pro/400.css";
import "@fontsource/be-vietnam-pro/500.css";
import "@fontsource/be-vietnam-pro/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource-variable/literata";
import "@/styles/theme.css";

import { Shell } from "@/app/Shell";
import { ToastProvider } from "@/components/ui/Toast";
import { LibraryPage } from "@/routes/LibraryPage";
import { EbookPage } from "@/routes/EbookPage";
import { ChapterComparePage } from "@/routes/ChapterComparePage";
import { QueuePage } from "@/routes/QueuePage";
import { LogsPage } from "@/routes/LogsPage";
import { ConnectionPage } from "@/routes/ConnectionPage";
import { PlaceholderPage } from "@/routes/PlaceholderPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 },
  },
});

// Bản web chạy dưới /app/; bản Tauri build với base "./" (đường dẫn tương đối
// cho asset) nhưng router vẫn phải neo ở gốc.
const basename = import.meta.env.BASE_URL.startsWith("/") ? import.meta.env.BASE_URL : "/";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter basename={basename}>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<LibraryPage />} />
              <Route path="ebooks/:slug" element={<EbookPage />} />
              <Route path="ebooks/:slug/chapters/:index" element={<ChapterComparePage />} />
              <Route path="queue" element={<QueuePage />} />
              <Route path="logs" element={<LogsPage />} />
              <Route path="connection" element={<ConnectionPage />} />
              <Route path="dashboard" element={<PlaceholderPage title="Bảng điều khiển" />} />
              <Route path="sources" element={<PlaceholderPage title="Nguồn" />} />
              <Route path="idioms" element={<PlaceholderPage title="Từ điển chung" />} />
              <Route path="automation" element={<PlaceholderPage title="Tự động hóa" />} />
              <Route path="storage" element={<PlaceholderPage title="Lưu trữ" />} />
              <Route path="wireguard" element={<PlaceholderPage title="WireGuard" />} />
              <Route path="*" element={<PlaceholderPage title="Không có trang này" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
