import { useCallback, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface EbookSummary {
  slug: string;
  name: string;
  title: string;
  author: string;
  archived: boolean;
  in_library: boolean;
  toc_url: string;
  translate_type: string;
  total: number;
  raw_count: number;
  translated_count: number;
  strip: string;
  counts: Record<string, number>;
  epub_exists: boolean;
  epub_size: number;
}

export interface LibraryResponse {
  ebooks: EbookSummary[];
  archived_count: number;
}

export function libraryKey(showArchived: boolean) {
  return ["library", showArchived] as const;
}

export function useLibrary(showArchived = false) {
  return useQuery({
    queryKey: libraryKey(showArchived),
    queryFn: () =>
      api.get<LibraryResponse>(`/api/ui/library?show_archived=${showArchived ? 1 : 0}`),
  });
}

/* ── Truyện đang làm việc ────────────────────────────────────────────────
   Phần lớn công việc trong app diễn ra BÊN TRONG một truyện (chương, glossary,
   nhân vật, cài đặt, đọc). Giữ lựa chọn này ở một chỗ để thanh điều hướng mở
   thẳng vào truyện đó thay vì bắt quay lại Thư viện mỗi lần.                */

const BOOK_KEY = "n2e-current-book";
const listeners = new Set<() => void>();

function currentSlug(): string {
  return localStorage.getItem(BOOK_KEY) ?? "";
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useCurrentBook(): [string, (slug: string) => void] {
  const slug = useSyncExternalStore(subscribe, currentSlug, () => "");
  const select = useCallback((next: string) => {
    if (next) localStorage.setItem(BOOK_KEY, next);
    else localStorage.removeItem(BOOK_KEY);
    listeners.forEach((fn) => fn());
  }, []);
  return [slug, select];
}
