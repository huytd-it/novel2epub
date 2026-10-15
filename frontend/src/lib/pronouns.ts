import { api } from "./api";

export type PronounBranch = "ai" | "local_mt";
export type DialogueMarks = "standard" | "single_chinese" | "parentheses";
export const DIALOGUE_MARK_LABELS: Record<DialogueMarks, string> = {
  standard: "Ngoặc kép thông dụng (hiện tại)",
  single_chinese: "Chỉ nháy đơn / dấu thoại Trung",
  parentheses: "Chỉ ngoặc đơn",
};
export const DIALOGUE_MARK_EXAMPLES: Record<DialogueMarks, string> = {
  standard: '"…" · “…” · «…» · 「…」 · 『…』',
  single_chinese: "'…' · ‘…’ · “…” · 「…」 · 『…』",
  parentheses: "(…) · （…）",
};
export interface PronounScope { branch: PronounBranch; indexes: number[]; dialogue_marks: DialogueMarks }
export interface PronounPreview extends PronounScope {
  token: string;
  scanned: number;
  unchanged: number;
  replacements: number;
  skipped: { index: number; reason: string }[];
  chapters: { index: number; title: string; revision: number; replacements: number; diff: string }[];
}
export interface PronounApplied {
  applied: number[];
  failed: { index: number; code: string; error: string }[];
  replacements: number;
}
export const pronounsApi = {
  preview: (slug: string, scope: PronounScope) =>
    api.post<PronounPreview>(`/api/ui/ebooks/${encodeURIComponent(slug)}/pronouns/preview`, { body: scope, signal: AbortSignal.timeout(60_000) }),
  apply: (slug: string, preview: PronounPreview) =>
    api.post<PronounApplied>(`/api/ui/ebooks/${encodeURIComponent(slug)}/pronouns/apply`, {
      body: { branch: preview.branch, indexes: preview.indexes, dialogue_marks: preview.dialogue_marks, token: preview.token, confirmed: true },
      signal: AbortSignal.timeout(60_000),
    }),
};
