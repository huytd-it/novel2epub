import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

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
    mutationFn: (vars: { id: string; steps: string[]; schedule: string; enabled: boolean }) =>
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
