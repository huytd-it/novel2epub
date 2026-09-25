import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface AssistantThread {
  id: number;
  ebook_slug: string;
  provider_base_url: string;
  model: string;
  created_at: string;
}

export interface AssistantMessage {
  id: number;
  thread_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface AssistantDefaults {
  provider_base_url: string;
  model: string;
  api_key_configured: boolean;
  timeout_seconds: number;
}

const threadsKey = (slug: string) => ["assistant-threads", slug] as const;
const threadKey = (slug: string, id: number) => ["assistant-thread", slug, id] as const;

export function useAssistantDefaults(slug: string) {
  return useQuery({
    queryKey: ["assistant-defaults", slug],
    queryFn: () => api.get<AssistantDefaults>(`/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/defaults`),
    enabled: Boolean(slug),
    staleTime: 30_000,
  });
}

export function useAssistantThreads(slug: string) {
  return useQuery({
    queryKey: threadsKey(slug),
    queryFn: () =>
      api.get<{ threads: AssistantThread[] }>(
        `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads`,
      ),
    enabled: Boolean(slug),
  });
}

export function useAssistantThread(slug: string, threadId: number | null) {
  return useQuery({
    queryKey: threadKey(slug, threadId ?? 0),
    queryFn: () =>
      api.get<{ thread: AssistantThread; messages: AssistantMessage[] }>(
        `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads/${threadId}`,
      ),
    enabled: Boolean(slug) && threadId != null && threadId > 0,
  });
}

function useInvalidateAssistant(slug: string) {
  const client = useQueryClient();
  return (threadId?: number) => {
    client.invalidateQueries({ queryKey: threadsKey(slug) });
    if (threadId) client.invalidateQueries({ queryKey: threadKey(slug, threadId) });
  };
}

export function useCreateAssistantThread(slug: string) {
  const invalidate = useInvalidateAssistant(slug);
  return useMutation({
    mutationFn: (input: { provider_base_url?: string; model?: string }) =>
      api.post<{ thread: AssistantThread }>(
        `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads`,
        { body: input },
      ),
    onSuccess: () => invalidate(),
  });
}

export function usePatchAssistantThread(slug: string, threadId: number) {
  const invalidate = useInvalidateAssistant(slug);
  return useMutation({
    mutationFn: (input: { provider_base_url?: string; model?: string }) =>
      api.patch<{ thread: AssistantThread }>(
        `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads/${threadId}`,
        { body: input },
      ),
    onSuccess: () => invalidate(threadId),
  });
}

export function useDeleteAssistantThread(slug: string) {
  const invalidate = useInvalidateAssistant(slug);
  return useMutation({
    mutationFn: (threadId: number) =>
      api.del<{ ok: boolean }>(
        `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads/${threadId}`,
      ),
    onSuccess: () => invalidate(),
  });
}

export interface ChatInput {
  content: string;
  chapter_index?: number | null;
  selection?: string;
}

export interface PreviewApply {
  endpoint: string;
  body: Record<string, unknown>;
}

export interface FindReplaceItem {
  chapter_index: number;
  chapter_title?: string;
  para_index: number;
  before: string;
  after: string;
  group: number;
}

export interface PreviewCard {
  kind: "paragraph" | "glossary" | "find_replace";
  title: string;
  before?: string;
  after?: string;
  deleted?: boolean;
  entries?: { source: string; target: string; kind: string; error: string }[];
  entries_truncated?: boolean;
  total_matches?: number;
  has_errors?: boolean;
  groups?: { find: string; replace: string; regex: boolean; count: number }[];
  items?: FindReplaceItem[];
  truncated?: boolean;
  source?: string;
  apply: PreviewApply;
}

export interface ToolTrace {
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
}

export interface ChatResult {
  thread_id: number;
  message_id: number;
  reply: string;
  tool_calls: ToolTrace[];
  previews: PreviewCard[];
}

export async function sendAssistantChat(
  slug: string,
  threadId: number,
  input: ChatInput,
): Promise<ChatResult> {
  return api.post(
    `/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/threads/${threadId}/chat`,
    {
      body: {
        content: input.content,
        chapter_index: input.chapter_index ?? null,
        selection: input.selection ?? "",
      },
    },
  );
}

/** Ghi sau khi tick xác nhận preview: endpoint là `edits/apply`,
 * `glossary/apply` hoặc `find-replace/apply` theo thẻ preview. */
export async function applyPreview(
  slug: string,
  endpoint: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  return api.post(`/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/${endpoint}`, {
    body,
  });
}

export interface FillContextInput {
  chapter_indexes?: number[];
  min_frequency?: number;
  max_candidates?: number;
  with_retranslate?: boolean;
  with_characters?: boolean;
  model_override?: string;
}

/** Fill ngữ cảnh nặng (AI dịch lại + trích nhân vật) qua job nền
 * category=translate — tiến độ xem ở `/queue`. */
export async function fillContext(
  slug: string,
  input: FillContextInput,
): Promise<{ started: boolean; queue_url: string }> {
  return api.post(`/api/ui/ebooks/${encodeURIComponent(slug)}/assistant/fill-context`, {
    body: input,
  });
}

/** Thread đang chọn cho mỗi ebook — lưu localStorage theo slug, mở lại vẫn giữ. */
export function threadStorageKey(slug: string) {
  return `n2e-assistant-thread-${slug}`;
}

export function readSelectedThread(slug: string): number | null {
  if (!slug) return null;
  try {
    const raw = localStorage.getItem(threadStorageKey(slug));
    const id = raw ? Number(raw) : NaN;
    return Number.isFinite(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

export function writeSelectedThread(slug: string, threadId: number | null) {
  try {
    if (!slug) return;
    if (threadId && threadId > 0) localStorage.setItem(threadStorageKey(slug), String(threadId));
    else localStorage.removeItem(threadStorageKey(slug));
  } catch {
    /* bỏ qua khi không truy cập được localStorage */
  }
}
