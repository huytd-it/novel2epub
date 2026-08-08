import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

/**
 * Khoá của mỗi interface bên dưới khớp 1-1 với tham số `Form(...)` của các
 * endpoint lưu cũ trong `app/routes/settings.py` — xem
 * `app/routes/webui.py::ebook_settings` và `ebook_settings_save`. ĐỪNG đổi
 * tên trường ở đây một mình: `tests/test_ui_settings_contract.py` khoá lại
 * sự khớp này, lệch tên là mất dữ liệu lúc lưu mà không có lỗi nào báo.
 */
export interface NovelSettings {
  title: string;
  author: string;
  description: string;
  language: string;
  publisher: string;
  pubdate: string;
  subjects: string;
  series: string;
  series_index: string;
  identifier: string;
  cover_url: string;
}

export interface SourceSettings {
  toc_url: string;
  chapter_link_pattern: string;
  max_chapters: number;
  delay_seconds: number;
  max_workers: number;
  content_selector: string;
  scrapling_mode: string;
  solve_cloudflare: boolean;
  network_idle: boolean;
  impersonate: string;
  proxy: string;
  dns_over_https: boolean;
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
  headless: boolean;
  strip_patterns: string;
}

export interface TranslateSettings {
  type: string;
  base_url: string;
  api_key: string;
  model: string;
  timeout_seconds: number;
  temperature: number;
  prompt_template: string;
  title_prompt_template: string;
  genre: string;
  tone: string;
  pronoun_policy: string;
  title_mode: string;
  han_viet_level: string;
  keep_paragraphs: boolean;
  delay_seconds: number;
  max_workers: number;
  source_language: string;
  local_model: string;
  retry_attempts: number;
  retry_delay_seconds: number;
  chunk_max_chars: number;
  chunk_overlap_paragraphs: number;
  hachimimt_model_key: string;
  hachimimt_backend: string;
  hachimimt_beam_size: number;
  hachimimt_chunk_mode: string;
  batch_size: number;
  prompt_max_chars: number;
  auto_cleanup_han: boolean;
  cleanup_han_engine: string;
  cleanup_han_max_chars: number;
  cleanup_han_retries: number;
}

export interface AiSettings {
  base_url: string;
  api_key: string;
  model: string;
  timeout_seconds: number;
  temperature: number;
}

export interface ReaderSettings {
  url: string;
  service_key: string;
  timeout_seconds: number;
  batch_size: number;
  push_anchors: boolean;
  reader_slug: string;
  free_chapters: number;
  published: boolean;
}

export interface OutputSettings {
  data_dir: string;
  epub_path: string;
  crawl_max_workers: number;
  translate_max_workers: number;
}

export interface SettingsMeta {
  source_name: string;
  source_detected: boolean;
  source_presets: string[];
  overridden_fields: string[];
  genres: { value: string; label: string }[];
}

export interface EbookSettings {
  slug: string;
  novel: NovelSettings;
  source: SourceSettings;
  translate: TranslateSettings;
  ai: AiSettings;
  reader: ReaderSettings;
  output: OutputSettings;
  meta: SettingsMeta;
}

export type SettingsSection = "novel" | "source" | "translate" | "ai" | "reader" | "output";

export const settingsKey = (slug: string) => ["ebook-settings", slug] as const;

export function useEbookSettings(slug: string) {
  return useQuery({
    queryKey: settingsKey(slug),
    queryFn: () => api.get<EbookSettings>(`/api/ui/ebooks/${slug}/settings`),
    enabled: Boolean(slug),
  });
}

/**
 * Lưu một khối cấu hình. `section` chọn endpoint
 * `POST /api/ui/ebooks/{slug}/settings/{section}`, gọi thẳng hàm xử lý cũ
 * (`save_novel`, `save_source`, ...) — xem docstring của `ebook_settings_save`.
 */
export function useSaveSettings<S extends SettingsSection>(slug: string, section: S) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: EbookSettings[S]) =>
      api.post<{ saved: boolean }>(`/api/ui/ebooks/${slug}/settings/${section}`, {
        body: payload,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: settingsKey(slug) }),
  });
}
