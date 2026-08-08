import { useCallback, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { chapterKey } from "./ebook";

export interface NoteSuggestion {
  fixed_text: string;
  explanation: string;
  generated_at: string;
}

export interface Note {
  id: string;
  chapter_index: number;
  para_index: number;
  selected_text: string;
  para_text: string;
  note: string;
  status: "open" | "resolved" | "dismissed" | "stale";
  created_at: string;
  resolved_at: string | null;
  suggestion: NoteSuggestion | null;
}

export interface FindReplacePreviewItem {
  chapter_index: number;
  chapter_title: string;
  para_index: number;
  count: number;
  before: string;
  after: string;
}

export interface SearchHit {
  chapter_index: number;
  title: string;
  count: number;
  snippets: string[];
}

const notesKey = (slug: string, index: number) => ["notes", slug, index] as const;

export async function firstReadingIndex(slug: string): Promise<number> {
  const res = await api.get<{ index: number }>(`/api/ebooks/${slug}/read/first-index`);
  return res.index;
}

function invalidateChapter(client: ReturnType<typeof useQueryClient>, slug: string, index: number) {
  client.invalidateQueries({ queryKey: chapterKey(slug, index) });
  client.invalidateQueries({ queryKey: ["chapters", slug] });
}

export function useSaveChapterText(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { translated: string; expectedRev: number }) =>
      api.post<{ saved: boolean; word_count: number; revision: number }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/translated`,
        { body: { translated: vars.translated, expected_rev: vars.expectedRev } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useSaveParagraph(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { paraIndex: number; paraText: string; newText: string }) =>
      api.post<{ saved: boolean; deleted?: boolean; para?: string }>(
        `/api/ebooks/${slug}/chapters/${index}/para/save`,
        {
          form: {
            para_index: vars.paraIndex,
            para_text: vars.paraText,
            new_text: vars.newText,
          },
        },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useInsertParagraph(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { afterIndex: number; text: string }) =>
      api.post<{ saved: boolean; para: string; para_index: number }>(
        `/api/ebooks/${slug}/chapters/${index}/para/insert`,
        { form: { after_index: vars.afterIndex, text: vars.text } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useUpdateChapterTitle(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      api.post<{ title: string }>(`/api/ebooks/${slug}/chapters/${index}/title`, {
        form: { title },
      }),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useRevertEdits(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<{ reverted: boolean }>(`/api/ebooks/${slug}/chapters/${index}/revert-edits`),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

/* ── Ghi chú lỗi dịch ────────────────────────────────────────────────── */

export function useChapterNotes(slug: string, index: number) {
  return useQuery({
    queryKey: notesKey(slug, index),
    queryFn: () =>
      api.get<{ notes: Note[] }>(`/api/ebooks/${slug}/notes?chapter=${index}`).then((r) => r.notes),
    enabled: Boolean(slug) && Number.isFinite(index),
  });
}

function useNoteMutation<V>(slug: string, index: number, fn: (vars: V) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => client.invalidateQueries({ queryKey: notesKey(slug, index) }),
  });
}

export function useCreateNote(slug: string, index: number) {
  return useNoteMutation<{ paraIndex: number; selectedText: string; paraText: string; note: string }>(
    slug,
    index,
    (vars) =>
      api.post<Note>(`/api/ebooks/${slug}/notes`, {
        form: {
          chapter_index: index,
          para_index: vars.paraIndex,
          selected_text: vars.selectedText,
          para_text: vars.paraText,
          note: vars.note,
        },
      }),
  );
}

export function useUpdateNote(slug: string, index: number) {
  return useNoteMutation<{ id: string; note: string }>(slug, index, (vars) =>
    api.post<Note>(`/api/ebooks/${slug}/notes/${vars.id}/update`, { form: { note: vars.note } }),
  );
}

export function useDismissNote(slug: string, index: number) {
  return useNoteMutation<string>(slug, index, (id) =>
    api.post<Note>(`/api/ebooks/${slug}/notes/${id}/dismiss`),
  );
}

export function useDeleteNote(slug: string, index: number) {
  return useNoteMutation<string>(slug, index, (id) =>
    api.post(`/api/ebooks/${slug}/notes/${id}/delete`),
  );
}

export function useApplyNote(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<{ applied: boolean }>(`/api/ebooks/${slug}/notes/${id}/apply`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: notesKey(slug, index) });
      invalidateChapter(client, slug, index);
    },
  });
}

export function useAiFixNotes(slug: string, index: number) {
  return useNoteMutation<string[]>(slug, index, (ids) =>
    api.post<{ notes: Note[] }>(`/api/ebooks/${slug}/notes/ai-fix`, {
      form: { note_ids: ids.join(","), chapter_index: index },
    }),
  );
}

/* ── Tìm kiếm toàn văn ───────────────────────────────────────────────── */

export async function previewBookReplace(slug: string, find: string, replace: string, regex: boolean) {
  const params = new URLSearchParams({ find, replace, regex: String(regex), scope: "all" });
  return api.get<{ items: FindReplacePreviewItem[]; truncated: boolean }>(
    `/api/ebooks/${slug}/glossary/find-preview?${params}`,
  );
}

export async function applyBookReplace(
  slug: string,
  find: string,
  replace: string,
  regex: boolean,
  items: FindReplacePreviewItem[],
) {
  return api.post<{ replaced: number; chapters: number; stale: number }>(
    `/api/ebooks/${slug}/glossary/apply-selected`,
    {
      form: {
        find,
        replace,
        regex,
        selections: JSON.stringify(items.map((item) => ({
          chapter_index: item.chapter_index,
          para_index: item.para_index,
          expected: item.before,
        }))),
      },
    },
  );
}

export function useBookSearch(slug: string, query: string, regex: boolean, caseSensitive: boolean) {
  const q = query.trim();
  return useQuery({
    queryKey: ["book-search", slug, q, regex, caseSensitive],
    queryFn: () =>
      api.get<SearchHit[]>(
        `/api/ebooks/${slug}/search?q=${encodeURIComponent(q)}&regex=${regex}&case=${caseSensitive}`,
      ),
    enabled: Boolean(slug) && q.length > 0,
  });
}

/* ── Bookmark (client-side, không đụng backend) ─────────────────────── */

const bookmarkListeners = new Set<() => void>();

function bookmarkKey(slug: string) {
  return `n2e-bookmark-${slug}`;
}

function readBookmark(slug: string): number | null {
  const raw = localStorage.getItem(bookmarkKey(slug));
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

export function useBookmark(slug: string): [number | null, (index: number | null) => void] {
  const subscribe = useCallback((fn: () => void) => {
    bookmarkListeners.add(fn);
    return () => bookmarkListeners.delete(fn);
  }, []);
  const value = useSyncExternalStore(
    subscribe,
    () => readBookmark(slug),
    () => null,
  );
  const set = useCallback(
    (index: number | null) => {
      if (index === null) localStorage.removeItem(bookmarkKey(slug));
      else localStorage.setItem(bookmarkKey(slug), String(index));
      bookmarkListeners.forEach((fn) => fn());
    },
    [slug],
  );
  return [value, set];
}

/* ── Tuỳ chọn đọc: cỡ chữ, giữ nguyên qua các truyện ─────────────────── */

const FONT_KEY = "n2e-reader-font-size";
const fontListeners = new Set<() => void>();
const FONT_MIN = 15;
const FONT_MAX = 26;
const FONT_DEFAULT = 18;

function readFontSize(): number {
  const raw = Number(localStorage.getItem(FONT_KEY));
  return raw >= FONT_MIN && raw <= FONT_MAX ? raw : FONT_DEFAULT;
}

export interface ReaderPreferences {
  fontSize: number;
  fontFamily: "serif" | "sans" | "mono";
  lineHeight: number;
  contentWidth: number;
}

const PREFS_KEY = "n2e-reader-preferences-v2";
const DEFAULT_PREFS: ReaderPreferences = { fontSize: 18, fontFamily: "serif", lineHeight: 1.8, contentWidth: 720 };

let cachedReaderPreferences: ReaderPreferences | null = null;

function readReaderPreferences(): ReaderPreferences {
  let parsed: ReaderPreferences;
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") as Partial<ReaderPreferences>;
    parsed = {
      fontSize: Math.min(28, Math.max(14, Number(saved.fontSize) || DEFAULT_PREFS.fontSize)),
      fontFamily: ["serif", "sans", "mono"].includes(saved.fontFamily || "") ? saved.fontFamily! : "serif",
      lineHeight: Math.min(2.2, Math.max(1.4, Number(saved.lineHeight) || DEFAULT_PREFS.lineHeight)),
      contentWidth: Math.min(1000, Math.max(560, Number(saved.contentWidth) || DEFAULT_PREFS.contentWidth)),
    };
  } catch {
    parsed = DEFAULT_PREFS;
  }
  const prev = cachedReaderPreferences;
  if (
    prev &&
    prev.fontSize === parsed.fontSize &&
    prev.fontFamily === parsed.fontFamily &&
    prev.lineHeight === parsed.lineHeight &&
    prev.contentWidth === parsed.contentWidth
  ) {
    return prev;
  }
  cachedReaderPreferences = parsed;
  return parsed;
}

export function useReaderPreferences(): [ReaderPreferences, (patch: Partial<ReaderPreferences>) => void] {
  const subscribe = useCallback((fn: () => void) => {
    fontListeners.add(fn);
    return () => fontListeners.delete(fn);
  }, []);
  const preferences = useSyncExternalStore(subscribe, readReaderPreferences, () => DEFAULT_PREFS);
  const set = useCallback((patch: Partial<ReaderPreferences>) => {
    const next = { ...readReaderPreferences(), ...patch };
    cachedReaderPreferences = next;
    localStorage.setItem(PREFS_KEY, JSON.stringify(next));
    fontListeners.forEach((fn) => fn());
  }, []);
  return [preferences, set];
}

export function useReaderFontSize(): [number, (size: number) => void] {
  const subscribe = useCallback((fn: () => void) => {
    fontListeners.add(fn);
    return () => fontListeners.delete(fn);
  }, []);
  const size = useSyncExternalStore(subscribe, readFontSize, () => FONT_DEFAULT);
  const set = useCallback((next: number) => {
    const clamped = Math.min(FONT_MAX, Math.max(FONT_MIN, next));
    localStorage.setItem(FONT_KEY, String(clamped));
    fontListeners.forEach((fn) => fn());
  }, []);
  return [size, set];
}

/* ── Nhánh dịch: AI vs Local MT ──────────────────────────────────────────
   Hai nhánh độc lập, mỗi nhánh có bản dịch/tiêu đề/revision riêng. Nhánh
   đang hoạt động (`active_branch`) là thứ đi vào EPUB. Xem
   `novel2epub/revisions.py`.                                              */

export type Branch = "ai" | "local_mt";

export function useSetActiveBranch(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (branch: Branch) =>
      api.post<{ index: number; active: Branch }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/branches`,
        { body: { branch } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

/** Dịch lại chương này vào một nhánh (`force` để ghi đè bản đã có). */
export function useTranslateChapter(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { branch: Branch; force?: boolean }) =>
      api.post<{ started: boolean; branch: Branch }>(`/api/ui/ebooks/${slug}/translate`, {
        body: { branch: vars.branch, indexes: [index], force: vars.force ?? true },
      }),
    onSuccess: () => {
      invalidateChapter(client, slug, index);
      client.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

/** Biên tập AI chương này — sinh bản nháp, KHÔNG tự ghi đè bản dịch. */
export function useRewriteChapter(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (genre: string) =>
      api.post<{ started: boolean; genre: string }>(`/api/ui/ebooks/${slug}/rewrite`, {
        body: { indexes: [index], genre },
      }),
    onSuccess: () => {
      invalidateChapter(client, slug, index);
      client.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

/* ── Bản nháp AI (candidate) ─────────────────────────────────────────── */

export function useConfirmDraft(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (revisionId: number) =>
      api.post<{ applied: boolean }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/ai/rewrite/confirm`,
        { body: { revision_id: revisionId } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useDiscardDraft(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (revisionId: number) =>
      api.post<{ discarded: boolean }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/ai/rewrite/discard`,
        { body: { revision_id: revisionId } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

/* ── Thể loại dùng cho prompt biên tập ───────────────────────────────── */

export function useGenres() {
  return useQuery({
    queryKey: ["genres"],
    queryFn: () => api.get<{ genres: { value: string; label: string }[] }>("/api/ui/genres"),
    staleTime: Infinity,
  });
}
