import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export const AUTOMATION_STEP_META: Record<string, { name: string; description: string }> = {
  "fetch-toc": { name: "Cập nhật mục lục", description: "Lấy danh sách chương mới từ nguồn" },
  "crawl-new": { name: "Cào chương mới", description: "Tải nội dung gốc của các chương còn thiếu" },
  "translate-local-mt": { name: "Dịch Local MT", description: "Dịch nhanh bằng mô hình chạy cục bộ" },
  "translate-pending": { name: "LLM dịch", description: "Dịch các chương đang chờ bằng LLM" },
  "llm-edit": { name: "LLM biên tập", description: "Tạo bản nháp biên tập từ bản Local MT" },
  "cleanup-han": { name: "Dọn từ Hán", description: "Rà soát và làm sạch từ Hán còn sót" },
  build: { name: "Đóng gói EPUB", description: "Tạo lại tệp EPUB hoàn chỉnh" },
  "publish-reader": { name: "Đăng Reader", description: "Đồng bộ bản mới lên Reader" },
};

export function automationStepName(step: string) {
  return AUTOMATION_STEP_META[step]?.name ?? step;
}

export interface Automation {
  id: string;
  ebook: string;
  steps: string[];
  schedule: string;
  enabled: boolean;
  last_run_at: string;
  last_run_outcome: string;
  last_run_error: string;
  last_run_stats: Record<string, number>;
  crawl_workers: number;
  translate_workers: number;
  created_at: string;
  next_run: string;
}

export interface EbookOption {
  slug: string;
  title: string;
}

export interface AutomationOverview {
  automations: Automation[];
  ebooks: EbookOption[];
  steps: string[];
}

const key = ["automation"] as const;

export function useAutomationOverview() {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<AutomationOverview>("/api/ui/automation"),
    refetchInterval: 3000,
  });
}

function useInvalidate() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: key });
}

export interface AutomationInput {
  ebook: string;
  steps: string[];
  schedule: string;
  crawl_workers?: number;
  translate_workers?: number;
}

export function useCreateAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: AutomationInput) => api.post<Automation>("/api/ui/automation", { body: vars }),
    onSuccess: invalidate,
  });
}

export function useUpdateAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (vars: AutomationInput & { id: string; enabled: boolean }) =>
      api.post<{ ok: boolean }>(`/api/ui/automation/${vars.id}/update`, { body: vars }),
    onSuccess: invalidate,
  });
}

export function useDeleteAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean }>(`/api/ui/automation/${id}/delete`),
    onSuccess: invalidate,
  });
}

export function useRunAutomationNow() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean; job_id: string }>(`/api/ui/automation/${id}/run-now`),
    onSuccess: invalidate,
  });
}

export function useValidateSchedule() {
  return useMutation({
    mutationFn: (schedule: string) =>
      api.get<{ valid: boolean }>(`/api/automation/validate-schedule?schedule=${encodeURIComponent(schedule)}`),
  });
}
