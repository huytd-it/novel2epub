import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiBase, apiToken } from "./api";

export interface UploadPreview {
  title: string;
  author: string;
  slug: string;
  chapter_count: number;
  chapters_preview: string[];
  has_cover: boolean;
  filename: string;
}

export interface UploadCreateMeta {
  slug?: string;
  title?: string;
  author?: string;
  description?: string;
}

export interface UploadCreateResult {
  slug: string;
  title: string;
  chapter_count: number;
}

export interface UploadAppendResult {
  added: number;
  skipped: number;
  total: number;
  added_indexes: number[];
  skipped_titles: string[];
}

async function readUploadError(res: Response): Promise<string> {
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
async function postFile<T>(path: string, file: File, fields: Record<string, string | undefined>): Promise<T> {
  const form = new FormData();
  form.append("file", file, file.name);
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) form.append(key, value);
  }
  const headers: Record<string, string> = {};
  const token = apiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${apiBase()}${path}`, { method: "POST", headers, body: form });
  if (!res.ok) throw new ApiError(res.status, await readUploadError(res));
  return (await res.json()) as T;
}

export function previewUpload(file: File): Promise<UploadPreview> {
  return postFile<UploadPreview>("/api/ui/library/ebooks/upload/preview", file, {});
}

export function createFromUpload(file: File, meta: UploadCreateMeta): Promise<UploadCreateResult> {
  return postFile<UploadCreateResult>("/api/ui/library/ebooks/upload", file, {
    slug: meta.slug ?? "",
    title: meta.title ?? "",
    author: meta.author ?? "",
    description: meta.description ?? "",
  });
}

export function uploadChaptersToEbook(slug: string, file: File): Promise<UploadAppendResult> {
  return postFile<UploadAppendResult>(`/api/ui/ebooks/${encodeURIComponent(slug)}/chapters/upload`, file, {});
}

export function useUploadChaptersToEbook(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadChaptersToEbook(slug, file),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["chapters"] });
      client.invalidateQueries({ queryKey: ["ebook", slug] });
      client.invalidateQueries({ queryKey: ["library"] });
    },
  });
}

export function useCreateFromUpload() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, meta }: { file: File; meta: UploadCreateMeta }) => createFromUpload(file, meta),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["library"] });
    },
  });
}
