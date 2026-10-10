import { useCallback, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { chapterKey } from "./ebook";
import { queueKey } from "./queue";
import type { ValidationIssue } from "./validation";

export interface ProofreadingSnapshot {
  index: number; branch: string; revision: number; hash: string; title: string; text: string;
  draft?: boolean; draft_text?: string; draft_title?: string; display_title?: string; draft_hash?: string; issues?: ValidationIssue[]; error?: string;
}
export interface ProofreadingCandidate {
  before: string;
  before_title?: string;
  id?: number; status?: string; base: ProofreadingSnapshot; draft: boolean; draft_hash: string;
  after: string; title: string; diff: string; edits: { start: number; end: number; original: string; replacement: string }[];
}
export interface ProofreadingResult {
  index: number; error?: string; unresolved?: string; before: string; after: string; title: string;
  draft: boolean; committed?: boolean; base: ProofreadingSnapshot; candidate_id: number | null; candidate?: ProofreadingCandidate;
  codes?: string[]; audit?: string[]; counts?: Record<string, { before: number; after_algorithm: number }>;
}
export interface ProofreadingScanRow {
  index: number; title: string; issues: ValidationIssue[]; error?: string;
  stale?: boolean; checked_at?: number; source?: { branch: string; revision: number; hash: string } | null;
}
export interface ProofreadingScanReport {
  scan: true; checked: number; chapters: ProofreadingScanRow[];
  persisted?: boolean; total?: number; unchecked?: number; checked_at?: number;
}
export const proofreadingApi = {
  state: (slug: string) => api.get<ProofreadingScanReport>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/state`),
  scan: (slug: string) => api.post<{ job_id: string }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/scan`),
  scanResult: (slug: string, id: string) => api.get<ProofreadingScanReport>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/results/${encodeURIComponent(id)}`),
  analyze: (slug: string, indexes: number[], codes: string[], drafts: Record<string, unknown>) => api.post<{ chapters: ProofreadingSnapshot[]; codes: string[]; token: string }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/analyze`, { body: { indexes, codes, drafts } }),
  run: (slug: string, chapters: ProofreadingSnapshot[], codes: string[], instructions: string, token: string) => api.post<{ job_id: string }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/run`, { body: { chapters, codes, instructions, confirmed: true, token } }),
  book: (slug: string) => api.post<{ job_id: string }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/book-check`),
  candidate: (slug: string, index: number, id: number) => api.get<ProofreadingCandidate>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/candidates/${index}/${id}`),
  result: (slug: string, id: string) => api.get<{ chapters?: ProofreadingResult[]; issues?: { index: number; message: string; code: string }[] }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/results/${encodeURIComponent(id)}`),
  decide: (slug: string, items: { index: number; id: number; draft_text?: string; draft_title?: string }[], action: "apply" | "discard") => api.post<{ chapters: { index: number; id: number; ok: boolean; error?: string; draft?: boolean; after?: string; title?: string; audit?: string[] }[] }>(`/api/ui/ebooks/${encodeURIComponent(slug)}/proofreading/decide`, { body: { items, action } }),
};

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
  client.invalidateQueries({ queryKey: ["content-validation", slug] });
}

/** UUID v4 an toàn mọi context (http LAN, iframe, trình duyệt cũ).
    `crypto.randomUUID` chỉ có trong secure context nên gọi trực tiếp sẽ nổ
    "crypto.randomUUID is not a function" khi Lưu chương. */
export function newOperationId(): string {
  try {
    const c = globalThis.crypto as Crypto | undefined;
    if (c?.randomUUID) return c.randomUUID();
    if (c?.getRandomValues) {
      const b = new Uint8Array(16);
      c.getRandomValues(b);
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const hex = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
  } catch {
    /* rơi xuống fallback bên dưới */
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16);
    const v = ch === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function useSaveChapterText(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { translated: string; title?: string; expectedRev: number; branch?: string; expectedHash?: string; publicationBranch?: string; publicationTitle?: string; proofreadingCodes?: string[] }) =>
      api.post<{ saved: boolean; word_count: number; revision: number; content_hash: string }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/translated`,
        { body: { translated: vars.translated, title: vars.title, expected_rev: vars.expectedRev, branch: vars.branch, expected_hash: vars.expectedHash, expected_publication_branch: vars.publicationBranch, expected_publication_title: vars.publicationTitle, proofreading_codes: vars.proofreadingCodes, operation_id: newOperationId() } },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

export function useSaveRawText(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { raw: string; expectedRaw: string }) =>
      api.post<{ saved: boolean; raw_char_count: number }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/raw`,
        { body: { raw: vars.raw, expected_raw: vars.expectedRaw } },
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

/** Nguồn tìm/thay: bản dịch (mặc định) hoặc bản gốc raw. */
export type FindSource = "translated" | "raw";

/** Cả `/search` lẫn `/find-preview` đều không có chế độ phân biệt hoa/thường —
    API phía sau (`reader.py`, `glossary.py`) không nhận option case. UI không
    cung cấp nút đó để khỏi hứa điều không có. */

export async function previewBookReplace(
  slug: string,
  find: string,
  replace: string,
  regex: boolean,
  scope: "chapter" | "all" = "all",
  chapterIndex?: number,
  source: FindSource = "translated",
) {
  const params = new URLSearchParams({
    find,
    replace,
    regex: String(regex),
    scope,
    source,
  });
  if (scope === "chapter" && chapterIndex !== undefined) {
    params.set("chapter_index", String(chapterIndex));
  }
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
  source: FindSource = "translated",
  allMatches = false,
) {
  return api.post<{ replaced: number; chapters: number; stale: number }>(
    `/api/ebooks/${slug}/glossary/apply-selected`,
    {
      form: {
        find,
        replace,
        regex,
        source,
        all_matches: allMatches,
        selections: JSON.stringify(items.map((item) => ({
          chapter_index: item.chapter_index,
          para_index: item.para_index,
          expected: item.before,
        }))),
      },
    },
  );
}

export function useBookSearch(slug: string, query: string, regex: boolean, source: FindSource) {
  const q = query.trim();
  return useQuery({
    queryKey: ["book-search", slug, q, regex, source],
    queryFn: () =>
      api.get<SearchHit[]>(
        `/api/ebooks/${slug}/search?q=${encodeURIComponent(q)}&regex=${regex}&case=false&source=${source}`,
      ),
    enabled: Boolean(slug) && q.length > 0,
  });
}

/** Sau khi áp dụng thay thế — cập nhật mọi thứ đang hiển thị nội dung chương.
    `["chapter", slug]` là tiền tố của `chapterKey(slug, index)` nên làm mới mọi
    chương của truyện, kể cả chương đang xem. */
export function invalidateBookSearch(client: ReturnType<typeof useQueryClient>, slug: string) {
  client.invalidateQueries({ queryKey: ["book-search", slug] });
  client.invalidateQueries({ queryKey: ["find-preview", slug] });
  client.invalidateQueries({ queryKey: ["chapter", slug] });
  client.invalidateQueries({ queryKey: ["chapters", slug] });
}

/** Previews nằm trong drawer; owner state nên được lưu vào localStorage theo slug. */
export interface ChapterFindState {
  query: string;
  replacement: string;
  regex: boolean;
  source: FindSource;
}

const FIND_KEY_PREFIX = "n2e-find-v1";

export function loadFindState(slug: string): ChapterFindState {
  try {
    const raw = localStorage.getItem(`${FIND_KEY_PREFIX}:${slug}`);
    if (!raw) return { query: "", replacement: "", regex: false, source: "translated" };
    const parsed = JSON.parse(raw) as Partial<ChapterFindState>;
    return {
      query: typeof parsed.query === "string" ? parsed.query : "",
      replacement: typeof parsed.replacement === "string" ? parsed.replacement : "",
      regex: Boolean(parsed.regex),
      source: parsed.source === "raw" ? "raw" : "translated",
    };
  } catch {
    return { query: "", replacement: "", regex: false, source: "translated" };
  }
}

export function saveFindState(slug: string, state: ChapterFindState) {
  try {
    localStorage.setItem(`${FIND_KEY_PREFIX}:${slug}`, JSON.stringify(state));
  } catch {
    /* bỏ qua khi không truy cập được localStorage */
  }
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

/** Sửa/xóa KHỐI trong khung đối chiếu 3 cột. Xóa đồng bộ raw+MT+bản dịch
    active phía server trong một transaction; trả về revision mới. */
export interface CompareBlockEdit {
  op: "edit_raw" | "edit_translated" | "delete";
  branch?: Branch;
  block: number;
  raw_expected?: string;
  block_expected?: string;
  new_text?: string;
  revision: number;
}

export function useCompareBlockEdit(slug: string, index: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: CompareBlockEdit) =>
      api.post<{ saved?: boolean; deleted?: boolean; revision: number; reason: string }>(
        `/api/ui/ebooks/${slug}/chapters/${index}/compare/block`,
        { body: vars },
      ),
    onSuccess: () => invalidateChapter(client, slug, index),
  });
}

/** Dịch lại đi qua hợp đồng bulk-preview + confirm vì nó GHI ĐÈ bản dịch:
    UI mở `BulkPreviewDialog` (xem `components/chapter/BulkPreviewDialog.tsx`). */

/* ── Biên tập AI: ghi TRỰC TIẾP vào nhánh Local MT ─────────────────────── */

export interface AiEditDraftResult {
  status: "queued";
  job_id: string;
  /** Số chương thực sự vào job (đã có bản dịch Local MT). */
  queued: number;
  /** Số chương bị bỏ qua vì chưa có bản dịch Local MT. */
  skipped: number;
  indexes: number[];
  blocked: { index: number; reason: string }[];
}

/** Xếp job biên tập AI GHI TRỰC TIẾP vào nhánh `local_mt` (canonical). Đây là
    hành động GHI ĐÈ bản dịch nên body bắt buộc `confirm: true`; UI nên đi qua
    hợp đồng bulk-preview/confirm (action `ai-edit`) để xem trước số chương đủ
    điều kiện trước khi xác nhận. */
export function startAiEdit(slug: string, indexes: number[]) {
  return api.post<AiEditDraftResult>(`/api/ui/ebooks/${slug}/chapters/ai-edit`, {
    body: { indexes, confirm: true },
  });
}

/** Alias cũ của canonical `/ai-edit` — request shape giữ nguyên nhưng semantics
    nay cũng là ghi trực tiếp (không còn sinh bản nháp chờ duyệt). */
export function startAiEditDraft(slug: string, indexes: number[]) {
  return api.post<AiEditDraftResult>(`/api/ui/ebooks/${slug}/chapters/ai-edit-draft`, {
    body: { indexes },
  });
}

/** Câu thông báo dùng chung cho cả trang chương lẫn trang truyện. */
export function aiEditDraftMessage(result: AiEditDraftResult) {
  const base = `Đã xếp ${result.queued} chương vào hàng đợi biên tập AI.`;
  return result.skipped > 0
    ? `${base} Bỏ qua ${result.skipped} chương chưa có bản dịch Local MT.`
    : base;
}

export function useAiEdit(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (indexes: number[]) => startAiEdit(slug, indexes),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queueKey });
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
