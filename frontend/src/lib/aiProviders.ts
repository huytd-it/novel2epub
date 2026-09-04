import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

/** Preset provider AI OpenAI-compatible dùng lại (name → base_url) — chọn từ
    danh sách thay vì gõ tay mỗi lần cấu hình Global AI / AI riêng từng ebook. */
export interface AiProviderPreset {
  name: string;
  base_url: string;
}

const key = ["ai-providers"] as const;

export function useAiProviders() {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<{ presets: AiProviderPreset[] }>("/api/ui/ai-providers"),
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: key });
}

export function useSaveAiProvider() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (preset: AiProviderPreset) =>
      api.post<AiProviderPreset>("/api/ui/ai-providers", { body: preset }),
    onSuccess: invalidate,
  });
}

export function useDeleteAiProvider() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<{ ok: boolean }>(`/api/ui/ai-providers/${encodeURIComponent(name)}/delete`),
    onSuccess: invalidate,
  });
}
