import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiBase, apiToken } from "./api";

/** Summary đọc từ file package mà không ghi gì — cho UI duyệt trước khi nhập. */
export interface TransferPreview {
  slug: string;
  title: string;
  author: string;
  source_preset: string;
  source_url: string;
  chapters: number;
  has_raw: number;
  has_translated: number;
  glossary: number;
  characters: number;
  relations: number;
  notes: number;
  entity_overrides: number;
  has_cover: boolean;
  has_epub: boolean;
  exported_at: string;
  /** Slug này đã tồn tại trên app hiện tại — cần đổi slug hoặc tick ghi đè. */
  exists: boolean;
}

export interface TransferImportResult {
  slug: string;
  counts: {
    chapters: number;
    glossary: number;
    characters: number;
    relations: number;
    notes: number;
    automations: number;
  };
  warnings: string[];
}

async function readTransferError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return `${res.status} ${res.statusText}`;
  try {
    const data = JSON.parse(text) as { detail?: unknown; error?: unknown };
    const detail = data.detail ?? data.error;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    /* phản hồi không phải JSON — dùng nguyên văn bên dưới */
  }
  return text.slice(0, 400);
}

/** POST multipart/form-data (file + fields) — `api.post` không hỗ trợ file. */
async function postTransferFile<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
): Promise<T> {
  const form = new FormData();
  form.append("file", file, file.name);
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  const headers: Record<string, string> = {};
  const token = apiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${apiBase()}${path}`, { method: "POST", headers, body: form });
  if (!res.ok) throw new ApiError(res.status, await readTransferError(res));
  return (await res.json()) as T;
}

export function previewTransfer(file: File): Promise<TransferPreview> {
  return postTransferFile<TransferPreview>(
    "/api/ui/library/ebooks/transfer/preview",
    file,
    {},
  );
}

export function importTransfer(
  file: File,
  opts: { slug?: string; overwrite?: boolean },
): Promise<TransferImportResult> {
  return postTransferFile<TransferImportResult>(
    "/api/ui/library/ebooks/transfer/import",
    file,
    { slug: opts.slug ?? "", overwrite: opts.overwrite ? "1" : "" },
  );
}

export function useImportTransfer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, slug, overwrite }: { file: File; slug: string; overwrite: boolean }) =>
      importTransfer(file, { slug, overwrite }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["library"] });
    },
  });
}

/** Tải package chuyển app (.n2e.zip) của một ebook về máy. */
export async function downloadTransfer(slug: string, includeEpub: boolean): Promise<void> {
  const headers: Record<string, string> = {};
  const token = apiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(
    `${apiBase()}/api/ui/ebooks/${encodeURIComponent(slug)}/transfer/export?include_epub=${includeEpub ? "1" : "0"}`,
    { headers },
  );
  if (!res.ok) throw new ApiError(res.status, await readTransferError(res));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${slug}.n2e.zip`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}
