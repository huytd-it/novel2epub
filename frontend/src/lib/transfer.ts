import { useMutation, useQueryClient } from "@tanstack/react-query";
import { downloadBlob, postFile } from "./api";

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

export function previewTransfer(file: File): Promise<TransferPreview> {
  return postFile<TransferPreview>(
    "/api/ui/library/ebooks/transfer/preview",
    file,
    {},
  );
}

export function importTransfer(
  file: File,
  opts: { slug?: string; overwrite?: boolean },
): Promise<TransferImportResult> {
  return postFile<TransferImportResult>(
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
export function downloadTransfer(slug: string, includeEpub: boolean): Promise<void> {
  return downloadBlob(
    `/api/ui/ebooks/${encodeURIComponent(slug)}/transfer/export?include_epub=${includeEpub ? "1" : "0"}`,
    `${slug}.n2e.zip`,
  );
}
