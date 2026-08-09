/**
 * Client cho hợp đồng bulk-preview / bulk-confirm (xem `novel2epub/bulk_contract.py`).
 *
 * Mọi hành động hàng loạt đều phải preview trước: preview KHÔNG đổi trạng thái
 * và không gọi model, chỉ trả token có hạn + đánh giá từng chương. Confirm nhận
 * token, xác thực (chưa dùng, chưa hết hạn, config còn khớp, workspace từng
 * chương còn khớp) rồi mới thực thi. Lệch → 409, phải preview lại.
 */
import { api } from "./api";

/** Action hợp đồng bulk — khớp `bulk_contract.BULK_ACTIONS`. */
export type BulkAction =
  | "translate"
  | "local-mt"
  | "ai-edit-draft"
  | "switch-branch"
  | "skip"
  | "unskip"
  | "delete-translation"
  | "build";

export interface BulkChapterItem {
  index: number;
  title: string;
  ok: boolean;
  reason: string;
  fingerprint: Record<string, unknown>;
  estimate: { input_tokens: number; output_tokens: number; cost_usd: number };
}

export interface BulkEstimate {
  eligible: number;
  blocked: number;
  blocked_indexes: number[];
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  per_chapter: { index: number; input_tokens: number; output_tokens: number; cost_usd: number }[];
}

export interface BulkPreview {
  token: string;
  action: BulkAction;
  branch: string;
  force: boolean;
  config_hash: string;
  total: number;
  eligible: number;
  blocked: number;
  chapters: BulkChapterItem[];
  estimates: BulkEstimate;
  expires_at: number;
}

export interface BulkConfirmResult {
  status: "queued" | "done";
  action: string;
  total?: number;
  changed?: number;
  branch?: string;
  exact_indexes?: number[];
  consumed?: boolean;
}

export function previewBulk(
  slug: string,
  params: { action: BulkAction; indexes: number[]; branch?: string; force?: boolean },
) {
  return api.post<BulkPreview>(`/api/ui/ebooks/${slug}/chapters/bulk-preview`, {
    body: params,
  });
}

export function confirmBulk(slug: string, token: string) {
  return api.post<BulkConfirmResult>(`/api/ui/ebooks/${slug}/chapters/bulk-confirm`, {
    body: { token },
  });
}
