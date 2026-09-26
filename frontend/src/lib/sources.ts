import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface SourcePreset {
  name: string;
  engine: string;
  url: string;
  domains: string;
  chapter_link_pattern: string;
  content_selector: string;
  toc_selector: string;
  chapter_title_selector: string;
  title_selector: string;
  author_selector: string;
  desc_selector: string;
  cover_selector: string;
  cover_url_pattern: string;
  encoding: string;
  user_agent: string;
  headless: boolean;
  magic: boolean;
  js_code: string;
  delay_seconds: number;
  next_page_selector: string;
  next_page_url_pattern: string;
  max_pages_per_chapter: number;
  toc_next_page_selector: string;
  toc_max_pages: number;
  retry_attempts: number;
  retry_delay_seconds: number;
  retry_backoff: number;
  retry_max_delay_seconds: number;
  retry_respect_retry_after: boolean;
  scrapling_mode: string;
  solve_cloudflare: boolean;
  network_idle: boolean;
  impersonate: string;
  proxy: string;
  dns_over_https: boolean;
  concurrency_cap: number;
  strip_patterns: string[];
}

export interface ValidationEntry {
  ok: boolean;
  message: string;
  checked_at: number;
}

export interface SourcesOverview {
  presets: SourcePreset[];
  usage: Record<string, string[]>;
  validation: Record<string, ValidationEntry>;
}

const key = ["sources"] as const;

export function useSources() {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<SourcesOverview>("/api/ui/sources"),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: key });
}

export function useSavePreset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (preset: Partial<SourcePreset> & { name: string; rename_from?: string }) =>
      api.post<SourcePreset>("/api/ui/sources", { body: preset }),
    onSuccess: (_res, vars) => {
      client.invalidateQueries({ queryKey: key });
      // Đổi tên preset sửa cả `ebooks.source_preset` → thư viện phải vẽ lại,
      // không thì card truyện vẫn hiện tên nguồn cũ.
      if (vars.rename_from && vars.rename_from !== vars.name) {
        client.invalidateQueries({ queryKey: ["library"] });
      }
    },
  });
}

export function useDeletePreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) => api.post<{ ok: boolean }>(`/api/ui/sources/${encodeURIComponent(name)}/delete`),
    onSuccess: invalidate,
  });
}

export function useClonePreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { name: string; newName: string }) =>
      api.post<SourcePreset>(`/api/ui/sources/${encodeURIComponent(vars.name)}/clone`, {
        body: { new_name: vars.newName },
      }),
    onSuccess: invalidate,
  });
}

export function useTestPreset() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: { name: string; tocUrl: string }) =>
      api.post<{ started: boolean }>(`/api/ui/sources/${encodeURIComponent(vars.name)}/test`, {
        body: { toc_url: vars.tocUrl },
      }),
    onSuccess: invalidate,
  });
}

/* ── Đồng bộ hai chiều với file sources.yaml ──────────────────────────── */

export type SyncAction = "import" | "export" | "skip";
export type SyncStatus = "added" | "changed" | "db_only" | "same";

/** `import` = bản trong file thắng (ghi vào DB) · `export` = bản trong DB thắng
 *  (ghi ra file) · `skip` = không đụng bên nào. */
export const SYNC_ACTION_LABELS: Record<SyncAction, string> = {
  import: "File → DB",
  export: "DB → file",
  skip: "Bỏ qua",
};

export const SYNC_STATUS_META: Record<SyncStatus, { label: string; hint: string }> = {
  added: { label: "Chỉ có trong file", hint: "Thêm vào DB" },
  changed: { label: "Hai bên khác nhau", hint: "Chọn bên thắng" },
  db_only: { label: "Chỉ có trong DB", hint: "Ghi thêm vào file" },
  same: { label: "Giống hệt", hint: "Không cần làm gì" },
};

export interface SyncFieldDiff {
  key: string;
  file_value: unknown;
  db_value: unknown;
}

export interface SyncPresetDiff {
  name: string;
  status: SyncStatus;
  action: SyncAction;
  actions: SyncAction[];
  fields: SyncFieldDiff[];
}

export interface SyncPreview {
  path: string;
  layout: "flat" | "wrapped";
  exists: boolean;
  file_order: string[];
  presets: SyncPresetDiff[];
  warnings: string[];
  counts: Record<SyncStatus, number>;
}

export interface SyncReport {
  path: string;
  layout: "flat" | "wrapped";
  imported: string[];
  exported: string[];
  skipped: string[];
  file_written: boolean;
  backup: string;
  warnings: string[];
}

const SYNC_PATH_KEY = "n2e:sources-sync-path";

/** Đường dẫn file sync đã dùng lần trước — rỗng = mặc định `sources.yaml` cạnh DB. */
export function savedSyncPath(): string {
  try {
    return localStorage.getItem(SYNC_PATH_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveSyncPath(value: string) {
  try {
    const trimmed = value.trim();
    if (trimmed) localStorage.setItem(SYNC_PATH_KEY, trimmed);
    else localStorage.removeItem(SYNC_PATH_KEY);
  } catch {
    /* private mode — coi như không nhớ */
  }
}

export function useSyncPreview() {
  return useMutation({
    mutationFn: (filePath: string) =>
      api.post<SyncPreview>("/api/ui/sources/sync/preview", { body: { path: filePath } }),
  });
}

export function useSyncApply() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { path: string; choices: Record<string, SyncAction> }) =>
      api.post<SyncReport>("/api/ui/sources/sync/apply", { body: vars }),
    onSuccess: () => {
      // Sync có thể thêm/xoá/đổi preset nên thư viện cũng phải vẽ lại.
      client.invalidateQueries({ queryKey: key });
      client.invalidateQueries({ queryKey: ["library"] });
    },
  });
}

export const EMPTY_PRESET: SourcePreset = {
  name: "",
  engine: "scrapling",
  url: "",
  domains: "",
  chapter_link_pattern: ".*",
  content_selector: "",
  toc_selector: "",
  chapter_title_selector: "",
  title_selector: "",
  author_selector: "",
  desc_selector: "",
  cover_selector: "",
  cover_url_pattern: "",
  encoding: "",
  user_agent: "",
  // Khớp mặc định của dataclass `SourcePreset` (novel2epub/sources.py) — preset
  // mới không được vô tình mở browser hiện hình khi crawl / tải DOM.
  headless: true,
  magic: false,
  js_code: "",
  delay_seconds: 1,
  next_page_selector: "",
  next_page_url_pattern: "",
  max_pages_per_chapter: 10,
  toc_next_page_selector: "",
  toc_max_pages: 5,
  retry_attempts: 3,
  retry_delay_seconds: 5,
  retry_backoff: 2,
  retry_max_delay_seconds: 120,
  retry_respect_retry_after: true,
  scrapling_mode: "stealthy",
  solve_cloudflare: false,
  network_idle: true,
  impersonate: "",
  proxy: "",
  dns_over_https: false,
  concurrency_cap: 0,
  strip_patterns: [],
};
