import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router";

import "@fontsource-variable/bricolage-grotesque/wght.css";
import "@fontsource/be-vietnam-pro/400.css";
import "@fontsource/be-vietnam-pro/500.css";
import "@fontsource/be-vietnam-pro/600.css";
import "@fontsource/be-vietnam-pro/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource-variable/literata/wght.css";
import "@/styles/theme.css";

import { Shell } from "@/app/Shell";
import { ToastProvider } from "@/components/ui/Toast";
import { LibraryPage } from "@/routes/LibraryPage";
import { AddBookPage } from "@/routes/AddBookPage";
import { EbookPage } from "@/routes/EbookPage";
import { SettingsPage } from "@/routes/SettingsPage";
import { ChapterEntryPage } from "@/routes/ChapterEntryPage";
import { ChapterPage } from "@/routes/ChapterPage";
import { IdiomsPage } from "@/routes/IdiomsPage";
import { GlossaryPage } from "@/routes/GlossaryPage";
import { CharactersPage } from "@/routes/CharactersPage";
import { QueuePage } from "@/routes/QueuePage";
import { LogsPage } from "@/routes/LogsPage";
import { ConnectionPage } from "@/routes/ConnectionPage";
import { DashboardPage } from "@/routes/DashboardPage";
import { SourcesPage } from "@/routes/SourcesPage";
import { AutomationPage } from "@/routes/AutomationPage";
import { StoragePage } from "@/routes/StoragePage";
import { WireGuardPage } from "@/routes/WireGuardPage";
import { TailscalePage } from "@/routes/TailscalePage";
import { LocalMtPage } from "@/routes/LocalMtPage";
import { GlobalTranslatePage } from "@/routes/GlobalTranslatePage";
import { PlaceholderPage } from "@/routes/PlaceholderPage";

/** `/read/:index` cũ → `/chapters/:index`. Giữ để bookmark/link đã lưu không chết. */
function LegacyReadRedirect() {
  const { slug, index } = useParams();
  return <Navigate to={`/ebooks/${slug}/chapters/${index}`} replace />;
}

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
              <Route path="library/new" element={<AddBookPage />} />
              <Route path="ebooks/:slug" element={<EbookPage />} />
              {/* Một trang duy nhất cho mỗi chương: đọc, sửa, đối chiếu, duyệt
                  bản nháp AI. `/read` cũ giữ lại để link đã lưu không chết. */}
              <Route path="ebooks/:slug/chapters" element={<ChapterEntryPage />} />
              <Route path="ebooks/:slug/chapters/:index" element={<ChapterPage />} />
              <Route path="ebooks/:slug/read" element={<ChapterEntryPage />} />
              <Route path="ebooks/:slug/read/:index" element={<LegacyReadRedirect />} />
              <Route path="ebooks/:slug/settings" element={<SettingsPage />} />
              <Route path="ebooks/:slug/glossary" element={<GlossaryPage />} />
              <Route path="ebooks/:slug/characters" element={<CharactersPage />} />
              <Route path="queue" element={<QueuePage />} />
              <Route path="logs" element={<LogsPage />} />
              <Route path="connection" element={<ConnectionPage />} />
              <Route path="dashboard" element={<DashboardPage />} />
              <Route path="sources" element={<SourcesPage />} />
              <Route path="idioms" element={<IdiomsPage />} />
              <Route path="automation" element={<AutomationPage />} />
              <Route path="storage" element={<StoragePage />} />
              <Route path="wireguard" element={<WireGuardPage />} />
              <Route path="tailscale" element={<TailscalePage />} />
              <Route path="local-mt" element={<LocalMtPage />} />
              <Route path="translate-settings" element={<GlobalTranslatePage />} />
              <Route path="*" element={<PlaceholderPage title="Không có trang này" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
